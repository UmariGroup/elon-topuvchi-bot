"""Parser konveyeri: xom post -> (AI) -> e'lon -> dublikat -> ishonch balli.

Toifadan mustaqil: toifaga xos hamma narsa `Category` orqali keladi.
Har post faqat bir marta AI'ga yuboriladi; kunlik limit oshsa konveyer to'xtaydi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.categories import get_category
from elon.config import Settings
from elon.db.models import Listing, RawPost
from elon.db.session import SessionMaker
from elon.llm.client import LLMClient
from elon.llm.usage import budget_exceeded, notify_budget_exceeded, record_ai_call
from elon.pipeline.dedup import DedupKey, is_duplicate
from elon.pipeline.phones import hash_phone
from elon.pipeline.scoring import score_listing
from elon.timeutil import utcnow

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_TEXT_CHARS = 4000
DEDUP_WINDOW_DAYS = 30


@dataclass
class ParseStats:
    parsed: int = 0
    duplicates: int = 0
    skipped: int = 0
    failed: int = 0
    budget_stopped: bool = False

    def add(self, outcome: str) -> None:
        if outcome == "parsed":
            self.parsed += 1
        elif outcome == "duplicate":
            self.duplicates += 1
        elif outcome == "skipped":
            self.skipped += 1
        else:
            self.failed += 1


def _skip(post: RawPost, reason: str) -> str:
    post.status = "skipped"
    post.skip_reason = reason
    return "skipped"


async def _reuse_identical_text(session: AsyncSession, post: RawPost) -> str | None:
    """Aynan shu matn avval tahlil qilingan bo'lsa, AI'ni qayta chaqirmaymiz."""
    result = await session.execute(
        select(RawPost)
        .where(
            RawPost.text_hash == post.text_hash,
            RawPost.category == post.category,
            RawPost.id != post.id,
            RawPost.status.in_(("parsed", "skipped")),
        )
        .order_by(RawPost.id)
        .limit(1)
    )
    twin = result.scalar_one_or_none()
    if twin is None:
        return None
    if twin.status == "skipped":
        return _skip(post, twin.skip_reason or "same_as_skipped")
    listing = (
        await session.execute(select(Listing).where(Listing.raw_post_id == twin.id))
    ).scalar_one_or_none()
    if listing is None:
        return None
    canonical = listing
    if listing.duplicate_of_id is not None:
        canonical = await session.get(Listing, listing.duplicate_of_id) or listing
    canonical.last_seen_at = max(canonical.last_seen_at, post.posted_at)
    post.status = "skipped"
    post.skip_reason = "exact_duplicate"
    return "duplicate"


async def _find_duplicate(session: AsyncSession, listing: Listing, text: str) -> Listing | None:
    conditions = []
    if listing.phone_hash is not None:
        conditions.append(Listing.phone_hash == listing.phone_hash)
    if listing.segment is not None:
        conditions.append(Listing.segment == listing.segment)
    if not conditions:
        return None
    since = listing.posted_at - timedelta(days=DEDUP_WINDOW_DAYS)
    rows = await session.execute(
        select(Listing, RawPost.text)
        .join(RawPost, RawPost.id == Listing.raw_post_id)
        .where(
            Listing.category == listing.category,
            Listing.duplicate_of_id.is_(None),
            Listing.id != listing.id,
            Listing.last_seen_at >= since,
            or_(*conditions),
        )
        .order_by(Listing.id)
    )
    new_key = DedupKey(text, listing.phone_hash, listing.price_usd, listing.segment)
    for candidate, candidate_text in rows:
        old_key = DedupKey(
            candidate_text, candidate.phone_hash, candidate.price_usd, candidate.segment
        )
        if is_duplicate(new_key, old_key):
            return candidate
    return None


async def process_post(
    session: AsyncSession, llm: LLMClient, settings: Settings, post: RawPost, now: datetime
) -> str:
    """Bitta postni qayta ishlaydi. Natija: parsed | duplicate | skipped | failed | retry."""
    category = get_category(post.category)
    if category is None:
        return _skip(post, "unknown_category")
    reason = category.prefilter(post.text)
    if reason is not None:
        return _skip(post, reason)
    reused = await _reuse_identical_text(session, post)
    if reused is not None:
        return reused

    post.attempts += 1
    try:
        result = await llm.call_tool(
            model=settings.parser_model,
            system=category.parser_system_prompt,
            messages=[
                {"role": "user", "content": f"<post>\n{post.text[:MAX_TEXT_CHARS]}\n</post>"}
            ],
            tool=category.parser_tool,
            max_tokens=700,
        )
    except Exception as exc:
        log.warning("Post %s tahlilida xato: %s", post.id, type(exc).__name__)
        if post.attempts >= MAX_ATTEMPTS:
            post.status = "failed"
            return "failed"
        return "retry"

    await record_ai_call(
        session,
        purpose="parse",
        model=settings.parser_model,
        usage=result.usage,
        now=now,
        raw_post_id=post.id,
    )
    extracted = category.build(result.data, text=post.text, usd_uzs_rate=settings.usd_uzs_rate)
    if extracted is None:
        return _skip(post, "not_listing")

    listing = Listing(
        raw_post_id=post.id,
        category=post.category,
        source_url=post.source_url,
        posted_at=post.posted_at,
        last_seen_at=post.posted_at,
        created_at=now,
        location=extracted.location,
        segment=extracted.segment,
        price_usd=extracted.price_usd,
        price_original=extracted.price_original,
        currency=extracted.currency,
        summary=extracted.summary,
        is_agent=extracted.is_agent,
        phone_hash=(
            hash_phone(extracted.phone, settings.phone_hash_key) if extracted.phone else None
        ),
        has_photo=post.has_photo,
        photo_fp=post.photo_fp,
        deposit_requested=extracted.deposit_requested,
        prepay_before_viewing=extracted.prepay_before_viewing,
        attrs=extracted.attrs,
        trust_score=100,
        trust_reasons=[],
    )
    session.add(listing)
    await session.flush()

    original = await _find_duplicate(session, listing, post.text)
    outcome = "parsed"
    if original is not None:
        listing.duplicate_of_id = original.id
        listing.notify_checked_at = now  # dublikat bo'yicha bildirishnoma yuborilmaydi
        original.last_seen_at = max(original.last_seen_at, listing.posted_at)
        outcome = "duplicate"
    await score_listing(session, listing, post.text, now)
    post.status = "parsed"
    return outcome


async def process_pending(
    sessionmaker: SessionMaker,
    llm: LLMClient,
    settings: Settings,
    *,
    limit: int = 50,
    now: datetime | None = None,
) -> ParseStats:
    """Navbatdagi yangi postlarni qayta ishlaydi. Kunlik AI limiti oshsa to'xtaydi."""
    stats = ParseStats()
    async with sessionmaker() as session:
        ids = (
            (
                await session.execute(
                    select(RawPost.id)
                    .where(RawPost.status == "new")
                    .order_by(RawPost.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    for post_id in ids:
        moment = now or utcnow()
        async with sessionmaker() as session:
            if await budget_exceeded(session, settings.daily_budget_micro_usd, moment):
                if await notify_budget_exceeded(session, settings.daily_budget_micro_usd, moment):
                    log.warning("Kunlik AI limiti tugadi, tahlil to'xtatildi")
                await session.commit()
                stats.budget_stopped = True
                return stats
            post = await session.get(RawPost, post_id)
            if post is None or post.status != "new":
                continue
            outcome = await process_post(session, llm, settings, post, moment)
            await session.commit()
            if outcome != "retry":
                stats.add(outcome)
    return stats
