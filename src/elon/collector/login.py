"""Telegram akkauntga bir martalik kirish (session fayl yaratish).

    docker compose run --rm collector python -m elon.collector.login

Telefon raqam va Telegram yuborgan kod so'raladi. Session fayl TG_SESSION_PATH ga
yoziladi (docker volume). Bu faylni hech kimga bermang va repoga qo'shmang —
u akkauntga to'liq kirish huquqini beradi.
"""

from __future__ import annotations

import asyncio

from telethon import TelegramClient

from elon.config import get_settings


async def login() -> None:
    settings = get_settings()
    client = TelegramClient(
        settings.tg_session_path, settings.tg_api_id, settings.tg_api_hash.get_secret_value()
    )
    await client.start()  # telefon va kodni interaktiv so'raydi
    me = await client.get_me()
    print(f"Kirildi: id={getattr(me, 'id', '?')}. Session: {settings.tg_session_path}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(login())
