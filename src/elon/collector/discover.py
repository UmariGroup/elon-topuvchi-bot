"""Kanal nomzodlarini Telegram qidiruvi orqali topish (ro'yxatni 30–50 ga yetkazish uchun).

    docker compose run --rm collector python -m elon.collector.discover

Natijani ko'zdan kechirib, mos kanallarni config/channels.yaml ga qo'shing.
Qidiruv so'rovlari orasida pauza bor (limitga urilmaslik uchun).
"""

from __future__ import annotations

import asyncio
import sys

from telethon import TelegramClient
from telethon.tl import types
from telethon.tl.functions.contacts import SearchRequest

from elon.config import get_settings

DEFAULT_QUERIES = [
    "ijara kvartira toshkent",
    "kvartira ijara maklersiz",
    "toshkent arenda kvartira",
    "аренда квартир ташкент",
    "аренда ташкент без посредников",
    "ижара квартира тошкент",
    "talabalarga kvartira toshkent",
    "chilonzor ijara",
    "yunusobod ijara",
    "sergeli ijara",
]


async def discover(queries: list[str]) -> None:
    settings = get_settings()
    client = TelegramClient(
        settings.tg_session_path, settings.tg_api_id, settings.tg_api_hash.get_secret_value()
    )
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Avval: python -m elon.collector.login")
    seen: dict[str, tuple[int, str]] = {}
    for query in queries:
        result = await client(SearchRequest(q=query, limit=50))
        for chat in result.chats:
            if not isinstance(chat, types.Channel) or not chat.broadcast or not chat.username:
                continue
            seen[chat.username] = (chat.participants_count or 0, chat.title)
        await asyncio.sleep(4)
    await client.disconnect()
    for username, (members, title) in sorted(seen.items(), key=lambda item: -item[1][0]):
        print(f"- username: {username:<34} # {members:>7} a'zo | {title}")


if __name__ == "__main__":
    asyncio.run(discover(sys.argv[1:] or DEFAULT_QUERIES))
