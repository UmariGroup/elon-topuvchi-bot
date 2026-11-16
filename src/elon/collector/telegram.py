"""Telethon (MTProto) adapteri — `PostSource` protokolining Telegram amalga oshirilishi.

Bu fayl real Telegram akkauntsiz sinalmaydi; mantiq `service.py` da va testlangan.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from telethon import TelegramClient, errors, events, utils
from telethon.tl import types
from telethon.tl.functions.channels import JoinChannelRequest

from elon.collector.service import ChannelInfo, ChannelUnavailable
from elon.config import Settings
from elon.pipeline.ingest import PostData

log = logging.getLogger(__name__)

#: bir chaqiruvda kanaldan olinadigan eng ko'p post (birinchi yig'ishda himoya)
MAX_FETCH = 2000

NewPostHandler = Callable[[int, PostData], Awaitable[None]]


class NotAuthorized(RuntimeError):
    pass


def to_post(message: Any) -> PostData | None:
    """Telethon xabarini `PostData` ga aylantiradi. Xizmat xabarlari uchun `None`."""
    text = getattr(message, "message", None)
    date = getattr(message, "date", None)
    if not isinstance(text, str) or not isinstance(date, datetime):
        return None
    photo = getattr(message, "photo", None)
    fingerprint: str | None = None
    if photo is not None:
        for size in getattr(photo, "sizes", None) or []:
            if isinstance(size, types.PhotoStrippedSize):
                # Kichik inline-miniatyura: rasmni yuklab olmasdan "barmoq izi"
                fingerprint = hashlib.sha1(size.bytes, usedforsecurity=False).hexdigest()
                break
    posted_at = date if date.tzinfo is not None else date.replace(tzinfo=UTC)
    return PostData(
        message_id=int(message.id),
        posted_at=posted_at,
        text=text,
        has_photo=photo is not None,
        photo_fp=fingerprint,
    )


class TelegramSource:
    def __init__(self, settings: Settings) -> None:
        self.client = TelegramClient(
            settings.tg_session_path,
            settings.tg_api_id,
            settings.tg_api_hash.get_secret_value(),
            # Qisqa FloodWait'ni kutubxona o'zi kutadi, uzunini biz ushlaymiz
            flood_sleep_threshold=120,
            device_model="elon-collector",
            app_version="0.1",
        )

    async def start(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise NotAuthorized(
                "Telegram sessiyasi yo'q. Avval: docker compose run --rm collector "
                "python -m elon.collector.login"
            )

    async def _entity(self, username: str) -> Any:
        try:
            return await self.client.get_entity(username)
        except (
            errors.UsernameNotOccupiedError,
            errors.UsernameInvalidError,
            errors.ChannelPrivateError,
            ValueError,
        ) as exc:
            raise ChannelUnavailable(type(exc).__name__) from exc

    async def resolve(self, username: str) -> ChannelInfo:
        entity = await self._entity(username)
        if not isinstance(entity, types.Channel):
            raise ChannelUnavailable("kanal emas")
        return ChannelInfo(
            tg_id=int(utils.get_peer_id(entity)),
            title=getattr(entity, "title", None),
            joined=not bool(getattr(entity, "left", True)),
        )

    async def fetch(
        self, username: str, *, min_id: int = 0, since: datetime | None = None
    ) -> list[PostData]:
        entity = await self._entity(username)
        posts: list[PostData] = []
        try:
            async for message in self.client.iter_messages(
                entity, limit=MAX_FETCH, min_id=min_id, offset_date=since, reverse=True
            ):
                post = to_post(message)
                if post is not None:
                    posts.append(post)
        except errors.ChannelPrivateError as exc:
            raise ChannelUnavailable(type(exc).__name__) from exc
        return posts

    async def join(self, username: str) -> None:
        entity = await self._entity(username)
        try:
            await self.client(JoinChannelRequest(entity))
        except errors.UserAlreadyParticipantError:
            return
        except (
            errors.ChannelPrivateError,
            errors.ChannelsTooMuchError,
            errors.InviteRequestSentError,
        ) as exc:
            raise ChannelUnavailable(type(exc).__name__) from exc

    def on_new_post(self, handler: NewPostHandler) -> None:
        """A'zo bo'lingan kanallardagi yangi postlar real vaqtda keladi."""

        async def _on_message(event: Any) -> None:
            post = to_post(event.message)
            if post is None or event.chat_id is None:
                return
            try:
                await handler(int(event.chat_id), post)
            except Exception as exc:
                log.warning("Yangi postni saqlashda xato: %s", type(exc).__name__)

        self.client.add_event_handler(_on_message, events.NewMessage(incoming=True))


async def sleep_flood(exc: errors.FloodWaitError) -> None:
    """Telegram so'ragan vaqt + tasodifiy qo'shimcha kutish."""
    seconds = int(getattr(exc, "seconds", 60)) + random.randint(5, 30)  # noqa: S311
    log.warning("FloodWait: %s soniya kutyapman", seconds)
    await asyncio.sleep(seconds)
