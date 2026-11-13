"""Xom postni bazaga yozish. Toifadan va Telegram kutubxonasidan mustaqil."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from elon.db.models import Channel, RawPost
from elon.pipeline.dedup import text_hash


@dataclass(frozen=True)
class PostData:
    message_id: int
    posted_at: datetime
    text: str
    has_photo: bool = False
    photo_fp: str | None = None


def source_url(username: str, message_id: int) -> str:
    return f"https://t.me/{username}/{message_id}"


async def store_post(
    session: AsyncSession, channel: Channel, post: PostData, now: datetime
) -> RawPost | None:
    """Yangi postni saqlaydi. Matnsiz yoki avval saqlangan bo'lsa `None` qaytaradi."""
    channel.last_message_id = max(channel.last_message_id, post.message_id)
    text = post.text.strip()
    if not text:
        return None
    exists = await session.execute(
        select(RawPost.id).where(
            RawPost.channel_id == channel.id, RawPost.message_id == post.message_id
        )
    )
    if exists.first() is not None:
        return None
    raw = RawPost(
        channel_id=channel.id,
        message_id=post.message_id,
        category=channel.category,
        posted_at=post.posted_at,
        collected_at=now,
        text=text,
        text_hash=text_hash(text),
        has_photo=post.has_photo,
        photo_fp=post.photo_fp,
        source_url=source_url(channel.username, post.message_id),
        status="new",
    )
    try:
        async with session.begin_nested():
            session.add(raw)
    except IntegrityError:
        # Real vaqt va so'rov (polling) bir vaqtda yozgan bo'lishi mumkin
        return None
    return raw
