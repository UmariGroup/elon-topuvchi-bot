"""Yig'uvchi mantiqi. Telegram kutubxonasiga bog'liq emas — faqat `PostSource` protokoliga.

Shu sababli testlarda soxta manba bilan to'liq tekshiriladi, keyinchalik boshqa manba
(masalan boshqa loyiha uchun) ham shu interfeys orqali ulanadi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.db.models import Channel
from elon.pipeline.ingest import PostData, store_post

log = logging.getLogger(__name__)

JOIN_RETRY_DAYS = 3


class ChannelUnavailable(Exception):
    """Kanal topilmadi, yopiq yoki nomi noto'g'ri."""


@dataclass(frozen=True)
class ChannelInfo:
    tg_id: int
    title: str | None
    joined: bool


class PostSource(Protocol):
    async def resolve(self, username: str) -> ChannelInfo: ...

    async def fetch(
        self, username: str, *, min_id: int = 0, since: datetime | None = None
    ) -> list[PostData]: ...

    async def join(self, username: str) -> None: ...


async def poll_channel(
    session: AsyncSession,
    source: PostSource,
    channel: Channel,
    now: datetime,
    *,
    backfill_days: int,
) -> int:
    """Kanaldan yangi postlarni oladi. Birinchi marta — oxirgi `backfill_days` kun."""
    if channel.tg_id is None:
        info = await source.resolve(channel.username)
        channel.tg_id = info.tg_id
        channel.title = (info.title or "")[:255] or None
        if info.joined and channel.joined_at is None:
            channel.joined_at = now

    if channel.backfilled_at is None or channel.last_message_id == 0:
        # last_message_id == 0: kanalda hali birorta post ko'rilmagan. Bunda ham sana bo'yicha
        # olamiz — aks holda manba kanalning eng boshidan (yillar oldingi postlardan) boshlaydi.
        posts = await source.fetch(channel.username, since=now - timedelta(days=backfill_days))
    else:
        posts = await source.fetch(channel.username, min_id=channel.last_message_id)

    stored = 0
    for post in posts:
        if await store_post(session, channel, post, now) is not None:
            stored += 1
    if channel.backfilled_at is None:
        channel.backfilled_at = now
    channel.last_error = None
    return stored


def disable_channel(channel: Channel, reason: str) -> None:
    channel.enabled = False
    channel.last_error = reason[:255]


async def joins_in_last_day(session: AsyncSession, now: datetime) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Channel)
        .where(Channel.join_attempted_at >= now - timedelta(days=1))
    )
    return int(result.scalar_one())


async def pick_channel_to_join(
    session: AsyncSession, now: datetime, *, max_per_day: int
) -> Channel | None:
    """Kunlik limit ichida a'zo bo'lish kerak bo'lgan navbatdagi kanal (yoki `None`)."""
    if await joins_in_last_day(session, now) >= max_per_day:
        return None
    result = await session.execute(
        select(Channel)
        .where(
            Channel.enabled,
            Channel.tg_id.is_not(None),
            Channel.joined_at.is_(None),
            or_(
                Channel.join_attempted_at.is_(None),
                Channel.join_attempted_at < now - timedelta(days=JOIN_RETRY_DAYS),
            ),
        )
        .order_by(Channel.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def join_next(
    session: AsyncSession, source: PostSource, now: datetime, *, max_per_day: int
) -> Channel | None:
    """Bitta kanalga a'zo bo'ladi (limit ruxsat bersa). Urinish ham limitga hisoblanadi."""
    channel = await pick_channel_to_join(session, now, max_per_day=max_per_day)
    if channel is None:
        return None
    channel.join_attempted_at = now
    await session.flush()
    try:
        await source.join(channel.username)
    except ChannelUnavailable as exc:
        channel.last_error = f"join: {exc}"[:255]
        return channel
    channel.joined_at = now
    return channel
