"""Bot ichidagi fon ishlari: sinov tugashi, kuzatuv bildirishnomalari, admin xabarlari."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy import select

from elon.bot import texts
from elon.bot.keyboards import feedback_keyboard
from elon.config import Settings
from elon.db.models import AdminEvent
from elon.db.session import SessionMaker
from elon.services.users import expire_tick
from elon.services.watches import notify_tick
from elon.timeutil import utcnow

log = logging.getLogger(__name__)

TICK_SECONDS = 15


async def tick(bot: Bot, sessionmaker: SessionMaker, settings: Settings, now: datetime) -> None:
    # 1. Sinov/obuna muddati tugaganlar
    async with sessionmaker() as session:
        expired = [user.tg_id for user in await expire_tick(session, now)]
        await session.commit()
    for tg_id in expired:
        try:
            await bot.send_message(tg_id, texts.PAYMENT)
        except TelegramAPIError as exc:
            log.info("Muddat tugashi xabari yuborilmadi: %s", type(exc).__name__)

    # 2. Kuzatuvlar bo'yicha yangi e'lonlar
    async def send_listing(tg_id: int, text: str, listing_id: int) -> bool:
        try:
            await bot.send_message(tg_id, text, reply_markup=feedback_keyboard(listing_id))
        except TelegramForbiddenError:
            return False
        return True

    async with sessionmaker() as session:
        await notify_tick(session, settings, send_listing, now)
        await session.commit()

    # 3. Admin xabarlari (collector ham shu navbatga yozadi)
    async with sessionmaker() as session:
        events = list(
            (
                await session.execute(
                    select(AdminEvent)
                    .where(AdminEvent.sent_at.is_(None))
                    .order_by(AdminEvent.id)
                    .limit(20)
                )
            ).scalars()
        )
        for event in events:
            for admin_id in settings.admin_ids:
                try:
                    await bot.send_message(admin_id, event.text)
                except TelegramAPIError as exc:
                    log.warning("Admin'ga xabar yuborilmadi: %s", type(exc).__name__)
            event.sent_at = now
        await session.commit()


async def background_loop(bot: Bot, sessionmaker: SessionMaker, settings: Settings) -> None:
    while True:
        try:
            await tick(bot, sessionmaker, settings, utcnow())
        except Exception as exc:
            log.exception("Fon ishida xato: %s", type(exc).__name__)
        await asyncio.sleep(TICK_SECONDS)
