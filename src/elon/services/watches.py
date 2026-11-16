"""Kuzatuv: yangi mos e'lon chiqsa foydalanuvchiga yuborish."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.categories.rent.filter import RentFilter, matches
from elon.config import Settings
from elon.db.models import Feedback, Listing, Notification, User, Watch
from elon.services.search import CATEGORY, render_listing, view_of
from elon.services.users import Access, access_of
from elon.timeutil import tashkent_day_start

log = logging.getLogger(__name__)

#: (tg_id, matn, listing_id) -> True: yuborildi; False: foydalanuvchi botni bloklagan
SendListing = Callable[[int, str, int], Awaitable[bool]]

FRESH_HOURS = 24
BATCH = 100


async def set_watch(session: AsyncSession, user: User, flt: RentFilter, now: datetime) -> Watch:
    result = await session.execute(select(Watch).where(Watch.user_id == user.id))
    watch = result.scalar_one_or_none()
    if watch is None:
        watch = Watch(
            user_id=user.id, category=CATEGORY, filter=flt.model_dump(), active=True, created_at=now
        )
        session.add(watch)
    else:
        watch.filter = flt.model_dump()
        watch.active = True
        watch.created_at = now
    await session.flush()
    return watch


async def stop_watch(session: AsyncSession, user: User) -> bool:
    result = await session.execute(select(Watch).where(Watch.user_id == user.id))
    watch = result.scalar_one_or_none()
    if watch is None or not watch.active:
        return False
    watch.active = False
    return True


async def sent_today(session: AsyncSession, user_id: int, now: datetime) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.sent_at >= tashkent_day_start(now))
    )
    return int(result.scalar_one())


async def notify_tick(
    session: AsyncSession, settings: Settings, send: SendListing, now: datetime
) -> int:
    """Hali tekshirilmagan yangi e'lonlarni faol kuzatuvlarga solishtirib yuboradi."""
    listings = list(
        (
            await session.execute(
                select(Listing)
                .where(Listing.notify_checked_at.is_(None), Listing.duplicate_of_id.is_(None))
                .order_by(Listing.id)
                .limit(BATCH)
            )
        ).scalars()
    )
    if not listings:
        return 0
    rows = await session.execute(
        select(Watch, User).join(User, User.id == Watch.user_id).where(Watch.active)
    )
    watchers = [(watch, user) for watch, user in rows]
    counts: dict[int, int] = {}
    delivered = 0
    for listing in listings:
        listing.notify_checked_at = now
        if listing.category != CATEGORY:
            continue
        # Birinchi ishga tushishdagi eski (backfill) e'lonlar yuborilmaydi
        if listing.posted_at < now - timedelta(hours=FRESH_HOURS):
            continue
        if listing.trust_score < settings.min_notify_score:
            continue
        view = view_of(listing)
        for watch, user in watchers:
            if not watch.active or access_of(user, now) is Access.EXPIRED:
                continue
            # Faqat kuzatuv yoqilgandan keyin tushgan e'lonlar "yangi" hisoblanadi
            if listing.created_at < watch.created_at:
                continue
            try:
                flt = RentFilter.model_validate(watch.filter)
            except ValidationError:
                continue
            if not matches(flt, view):
                continue
            if user.id not in counts:
                counts[user.id] = await sent_today(session, user.id, now)
            if counts[user.id] >= settings.max_notifications_per_day:
                continue
            text = "🔔 Yangi mos e'lon\n\n" + render_listing(listing, now)
            try:
                ok = await send(user.tg_id, text, listing.id)
            except Exception as exc:
                log.warning("Bildirishnoma yuborilmadi (user %s): %s", user.id, type(exc).__name__)
                continue
            if not ok:
                watch.active = False
                continue
            session.add(Notification(user_id=user.id, listing_id=listing.id, sent_at=now))
            counts[user.id] += 1
            delivered += 1
    await session.flush()
    return delivered


async def save_feedback(
    session: AsyncSession, user: User, listing_id: int, value: int, now: datetime
) -> None:
    """👍/👎. Qayta bosilsa oxirgi baho saqlanadi."""
    result = await session.execute(
        select(Feedback).where(Feedback.user_id == user.id, Feedback.listing_id == listing_id)
    )
    feedback = result.scalar_one_or_none()
    if feedback is None:
        session.add(Feedback(user_id=user.id, listing_id=listing_id, value=value, created_at=now))
    else:
        feedback.value = value
        feedback.created_at = now
    await session.flush()
