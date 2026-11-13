"""Bazadan filtr bo'yicha eng yaxshi e'lonlarni topish."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.categories.rent.filter import ListingView, RentFilter, format_listing, matches, rank_score
from elon.config import Settings
from elon.db.models import Listing, RawPost, SearchLog, User
from elon.pipeline.scoring import score_listing

CATEGORY = "rent"
RESCORE_TOP = 20


def view_of(listing: Listing) -> ListingView:
    return ListingView(
        id=listing.id,
        location=listing.location,
        price_usd=listing.price_usd,
        attrs=listing.attrs or {},
        trust_score=listing.trust_score,
        last_seen_at=listing.last_seen_at,
    )


def render_listing(listing: Listing, now: datetime) -> str:
    return format_listing(
        summary=listing.summary,
        location=listing.location,
        price_usd=listing.price_usd,
        attrs=listing.attrs or {},
        is_agent=listing.is_agent,
        trust_score=listing.trust_score,
        trust_reasons=list(listing.trust_reasons or []),
        source_url=listing.source_url,
        posted_at=listing.last_seen_at,
        now=now,
    )


async def find_listings(
    session: AsyncSession,
    settings: Settings,
    flt: RentFilter,
    now: datetime,
    *,
    limit: int = 5,
) -> list[Listing]:
    since = now - timedelta(days=settings.search_max_age_days)
    query = select(Listing).where(
        Listing.category == CATEGORY,
        Listing.duplicate_of_id.is_(None),
        Listing.last_seen_at >= since,
    )
    if flt.districts:
        query = query.where(Listing.location.in_(flt.districts))
    if flt.price_max_usd is not None:
        query = query.where(Listing.price_usd <= flt.price_max_usd)
    candidates = [
        listing
        for listing in (await session.execute(query)).scalars()
        if matches(flt, view_of(listing))
    ]
    candidates.sort(key=lambda item: rank_score(flt, view_of(item), now), reverse=True)

    # Eng yaxshi nomzodlar uchun ballni hozirgi holat bo'yicha qayta hisoblaymiz
    # (e'lon eskirgan yoki telefon boshqa e'lonlarda ko'paygan bo'lishi mumkin).
    top = candidates[:RESCORE_TOP]
    for listing in top:
        text = (
            await session.execute(select(RawPost.text).where(RawPost.id == listing.raw_post_id))
        ).scalar_one()
        await score_listing(session, listing, text, now)
    top.sort(key=lambda item: rank_score(flt, view_of(item), now), reverse=True)
    return top[:limit]


async def run_search(
    session: AsyncSession,
    settings: Settings,
    user: User,
    flt: RentFilter,
    now: datetime,
    *,
    limit: int = 5,
) -> list[Listing]:
    """Qidiradi va so'rovni statistikaga yozadi."""
    found = await find_listings(session, settings, flt, now, limit=limit)
    session.add(
        SearchLog(user_id=user.id, filter=flt.model_dump(), result_count=len(found), created_at=now)
    )
    await session.flush()
    return found
