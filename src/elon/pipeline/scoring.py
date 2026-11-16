"""Qoidalar uchun kerakli ma'lumotni bazadan yig'ib, ishonch ballini hisoblaydi."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.db.models import Listing
from elon.rules import RuleInput, Trust, evaluate, market_median

MARKET_WINDOW_DAYS = 30


async def build_rule_input(
    session: AsyncSession, listing: Listing, text: str, now: datetime
) -> RuleInput:
    since = now - timedelta(days=MARKET_WINDOW_DAYS)
    own_ids = [listing.id]
    if listing.duplicate_of_id is not None:
        own_ids.append(listing.duplicate_of_id)

    median_usd: float | None = None
    if listing.segment is not None:
        prices = await session.execute(
            select(Listing.price_usd).where(
                Listing.category == listing.category,
                Listing.segment == listing.segment,
                Listing.duplicate_of_id.is_(None),
                Listing.price_usd.is_not(None),
                Listing.last_seen_at >= since,
                Listing.id.not_in(own_ids),
            )
        )
        median_usd = market_median([price for (price,) in prices if price is not None])

    other_with_phone = 0
    if listing.phone_hash is not None:
        other_with_phone = await _count(
            session,
            Listing.phone_hash == listing.phone_hash,
            Listing.duplicate_of_id.is_(None),
            Listing.last_seen_at >= since,
            Listing.id.not_in(own_ids),
        )

    photo_reused = 0
    if listing.photo_fp is not None and listing.phone_hash is not None:
        photo_reused = await _count(
            session,
            Listing.photo_fp == listing.photo_fp,
            Listing.phone_hash.is_not(None),
            Listing.phone_hash != listing.phone_hash,
            Listing.id.not_in(own_ids),
        )

    return RuleInput(
        price_usd=listing.price_usd,
        median_usd=median_usd,
        deposit_requested=listing.deposit_requested,
        prepay_before_viewing=listing.prepay_before_viewing,
        text=text,
        other_listings_with_phone=other_with_phone,
        has_photo=listing.has_photo,
        photo_reused_elsewhere=photo_reused,
        last_seen_at=listing.last_seen_at,
        now=now,
    )


async def _count(session: AsyncSession, *conditions: object) -> int:
    result = await session.execute(
        select(func.count()).select_from(Listing).where(*conditions)  # type: ignore[arg-type]
    )
    return int(result.scalar_one())


async def score_listing(session: AsyncSession, listing: Listing, text: str, now: datetime) -> Trust:
    """Ballni hisoblab, e'longa yozadi."""
    trust = evaluate(await build_rule_input(session, listing, text, now))
    listing.trust_score = trust.score
    listing.trust_reasons = trust.reasons
    return trust
