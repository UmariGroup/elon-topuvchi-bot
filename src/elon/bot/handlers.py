"""Bot handlerlari. Mantiq `elon.services` da — bu yerda faqat Telegram bilan bog'lash."""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from elon.bot import texts
from elon.bot.keyboards import (
    confirm_keyboard,
    contact_keyboard,
    delete_keyboard,
    feedback_keyboard,
    watch_keyboard,
)
from elon.config import Settings
from elon.db.models import User
from elon.db.session import SessionMaker
from elon.llm.client import LLMClient
from elon.services import users as user_service
from elon.services.chat import DailyLimitReached, current_filter, get_conversation, handle_message
from elon.services.search import render_listing, run_search
from elon.services.stats import collect_stats
from elon.services.users import Access, access_of, access_until
from elon.services.watches import save_feedback, set_watch, stop_watch
from elon.timeutil import utcnow

log = logging.getLogger(__name__)

_FEEDBACK = re.compile(r"^fb:(\d+):(-?1)$")


async def _active_user(session: AsyncSession, bot: Bot, tg_id: int) -> User | None:
    """Ro'yxatdan o'tgan va xizmati faol foydalanuvchini qaytaradi; aks holda xabar yuboradi."""
    user = await user_service.get_user(session, tg_id)
    if user is None:
        await bot.send_message(tg_id, texts.ASK_CONTACT, reply_markup=contact_keyboard())
        return None
    if access_of(user, utcnow()) is Access.EXPIRED:
        await bot.send_message(tg_id, texts.PAYMENT)
        return None
    return user


def build_router(settings: Settings) -> Router:
    router = Router(name="elon")
    router.message.filter(F.chat.type == "private")
    admin = F.from_user.id.in_(set(settings.admin_ids))

    # ------------------------------------------------------------ ro'yxat

    @router.message(CommandStart())
    async def on_start(message: Message, sessionmaker: SessionMaker) -> None:
        assert message.from_user is not None
        async with sessionmaker() as session:
            user = await user_service.get_user(session, message.from_user.id)
        if user is None:
            await message.answer(texts.ASK_CONTACT, reply_markup=contact_keyboard())
            return
        await message.answer(
            texts.welcome_back(access_until(user, utcnow())), reply_markup=ReplyKeyboardRemove()
        )

    @router.message(F.contact)
    async def on_contact(message: Message, sessionmaker: SessionMaker) -> None:
        assert message.from_user is not None and message.contact is not None
        # Birovning kontaktini yuborib ro'yxatdan o'tib bo'lmaydi
        if message.contact.user_id != message.from_user.id:
            await message.answer(texts.OWN_CONTACT_ONLY, reply_markup=contact_keyboard())
            return
        now = utcnow()
        async with sessionmaker() as session:
            user, created = await user_service.register(
                session,
                tg_id=message.from_user.id,
                phone=message.contact.phone_number,
                now=now,
                trial_days=settings.trial_days,
            )
            await session.commit()
        if created:
            text = texts.registered(settings.trial_days, user.trial_ends_at)
        else:
            text = texts.welcome_back(access_until(user, now))
        await message.answer(text, reply_markup=ReplyKeyboardRemove())

    # ------------------------------------------------------------ buyruqlar

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(texts.HELP.format(trial_days=settings.trial_days))

    @router.message(Command("stop"))
    async def on_stop(message: Message, bot: Bot, sessionmaker: SessionMaker) -> None:
        assert message.from_user is not None
        async with sessionmaker() as session:
            user = await user_service.get_user(session, message.from_user.id)
            if user is None:
                await message.answer(texts.NEED_REGISTRATION)
                return
            stopped = await stop_watch(session, user)
            await session.commit()
        await message.answer(texts.WATCH_OFF if stopped else texts.WATCH_NOT_ACTIVE)

    @router.message(Command("delete_me"))
    async def on_delete_me(message: Message) -> None:
        await message.answer(texts.DELETE_QUESTION, reply_markup=delete_keyboard())

    @router.callback_query(F.data.in_({"del:yes", "del:no"}))
    async def on_delete_confirm(
        callback: CallbackQuery, bot: Bot, sessionmaker: SessionMaker
    ) -> None:
        await callback.answer()
        if callback.data == "del:no":
            await bot.send_message(callback.from_user.id, texts.DELETE_CANCELLED)
            return
        async with sessionmaker() as session:
            await user_service.delete_user(session, callback.from_user.id)
            await session.commit()
        await bot.send_message(callback.from_user.id, texts.DELETED)

    # ------------------------------------------------------------ admin

    @router.message(Command("stats"), admin)
    async def on_stats(message: Message, sessionmaker: SessionMaker) -> None:
        async with sessionmaker() as session:
            stats = await collect_stats(session, utcnow())
        await message.answer(stats.format())

    @router.message(Command("activate"), admin)
    async def on_activate(
        message: Message, command: CommandObject, bot: Bot, sessionmaker: SessionMaker
    ) -> None:
        parts = (command.args or "").split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts) or int(parts[1]) < 1:
            await message.answer(texts.ADMIN_ACTIVATE_USAGE)
            return
        tg_id, days = int(parts[0]), min(int(parts[1]), 3650)
        async with sessionmaker() as session:
            user = await user_service.activate(session, tg_id=tg_id, days=days, now=utcnow())
            await session.commit()
        if user is None or user.paid_until is None:
            await message.answer(texts.ADMIN_USER_NOT_FOUND)
            return
        await message.answer(texts.activated_admin(tg_id, days, user.paid_until))
        try:
            await bot.send_message(tg_id, texts.activated_user(days, user.paid_until))
        except Exception as exc:
            log.warning("Faollashtirish xabari yuborilmadi: %s", type(exc).__name__)

    # ------------------------------------------------------------ suhbat

    @router.message(F.text)
    async def on_text(
        message: Message, bot: Bot, sessionmaker: SessionMaker, llm: LLMClient
    ) -> None:
        assert message.from_user is not None and message.text is not None
        if message.text.startswith("/"):
            await message.answer(texts.UNKNOWN_COMMAND)
            return
        tg_id = message.from_user.id
        async with sessionmaker() as session:
            user = await _active_user(session, bot, tg_id)
            if user is None:
                return
            await bot.send_chat_action(tg_id, "typing")
            try:
                reply = await handle_message(session, llm, settings, user, message.text, utcnow())
            except DailyLimitReached:
                await message.answer(texts.DAILY_LIMIT)
                return
            except Exception as exc:
                await session.rollback()
                log.exception("Suhbatda xato: %s", type(exc).__name__)
                await message.answer(texts.AI_ERROR)
                return
            await session.commit()
        await message.answer(reply.message)
        if reply.ready:
            await message.answer(
                texts.confirm(reply.filter.describe()), reply_markup=confirm_keyboard()
            )

    @router.callback_query(F.data == "f:edit")
    async def on_filter_edit(callback: CallbackQuery, bot: Bot, sessionmaker: SessionMaker) -> None:
        await callback.answer()
        async with sessionmaker() as session:
            user = await _active_user(session, bot, callback.from_user.id)
            if user is None:
                return
            conversation = await get_conversation(session, user, utcnow())
            conversation.state = "collecting"
            await session.commit()
        await bot.send_message(callback.from_user.id, texts.EDIT_PROMPT)

    @router.callback_query(F.data == "f:ok")
    async def on_filter_confirm(
        callback: CallbackQuery, bot: Bot, sessionmaker: SessionMaker
    ) -> None:
        await callback.answer(texts.SEARCHING)
        tg_id = callback.from_user.id
        now = utcnow()
        async with sessionmaker() as session:
            user = await _active_user(session, bot, tg_id)
            if user is None:
                return
            conversation = await get_conversation(session, user, now)
            if conversation.filter is None:
                await session.commit()
                await bot.send_message(tg_id, texts.NO_FILTER)
                return
            found = await run_search(session, settings, user, current_filter(conversation), now)
            conversation.state = "done"
            rendered = [(listing.id, render_listing(listing, now)) for listing in found]
            await session.commit()
        if not rendered:
            await bot.send_message(tg_id, texts.NO_RESULTS)
        for listing_id, text in rendered:
            await bot.send_message(tg_id, text, reply_markup=feedback_keyboard(listing_id))
        if rendered:
            await bot.send_message(tg_id, texts.RESULTS_FOOTER)
        await bot.send_message(tg_id, texts.WATCH_QUESTION, reply_markup=watch_keyboard())

    # ------------------------------------------------------------ kuzatuv va baho

    @router.callback_query(F.data.in_({"w:yes", "w:no"}))
    async def on_watch(callback: CallbackQuery, bot: Bot, sessionmaker: SessionMaker) -> None:
        await callback.answer()
        tg_id = callback.from_user.id
        if callback.data == "w:no":
            await bot.send_message(tg_id, texts.WATCH_DECLINED)
            return
        now = utcnow()
        async with sessionmaker() as session:
            user = await _active_user(session, bot, tg_id)
            if user is None:
                return
            conversation = await get_conversation(session, user, now)
            if conversation.filter is None:
                await session.commit()
                await bot.send_message(tg_id, texts.NO_FILTER)
                return
            await set_watch(session, user, current_filter(conversation), now)
            await session.commit()
        await bot.send_message(
            tg_id, texts.WATCH_ON.format(limit=settings.max_notifications_per_day)
        )

    @router.callback_query(F.data.regexp(_FEEDBACK))
    async def on_feedback(callback: CallbackQuery, sessionmaker: SessionMaker) -> None:
        match = _FEEDBACK.match(callback.data or "")
        assert match is not None
        async with sessionmaker() as session:
            user = await user_service.get_user(session, callback.from_user.id)
            if user is not None:
                await save_feedback(
                    session, user, int(match.group(1)), int(match.group(2)), utcnow()
                )
                await session.commit()
        await callback.answer(texts.FEEDBACK_THANKS)

    return router
