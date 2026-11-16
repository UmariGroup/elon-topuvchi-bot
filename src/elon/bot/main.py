"""Bot servisi. Ishga tushirish: `python -m elon.bot.main`"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from elon.bot.background import background_loop
from elon.bot.handlers import build_router
from elon.config import Settings, get_settings
from elon.db.session import SessionMaker, init_db, make_engine, make_sessionmaker
from elon.llm.client import AnthropicLLM, LLMClient
from elon.llm.pricing import price_for
from elon.logsetup import setup_logging

log = logging.getLogger("elon.bot")

COMMANDS = [
    BotCommand(command="start", description="Boshlash"),
    BotCommand(command="help", description="Yordam"),
    BotCommand(command="stop", description="Kuzatuvni o'chirish"),
    BotCommand(command="delete_me", description="Ma'lumotimni o'chirish"),
]


def build_dispatcher(settings: Settings, sessionmaker: SessionMaker, llm: LLMClient) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher["settings"] = settings
    dispatcher["sessionmaker"] = sessionmaker
    dispatcher["llm"] = llm
    dispatcher.include_router(build_router(settings))
    return dispatcher


async def run() -> None:
    setup_logging()
    settings = get_settings()
    price_for(settings.chat_model)  # noma'lum model bo'lsa darhol to'xtaydi
    engine = make_engine(settings.database_url.get_secret_value())
    await init_db(engine)
    sessionmaker = make_sessionmaker(engine)
    llm = AnthropicLLM(settings.anthropic_api_key.get_secret_value())

    bot = Bot(settings.telegram_bot_token.get_secret_value())
    dispatcher = build_dispatcher(settings, sessionmaker, llm)
    background: asyncio.Task[None] | None = None
    try:
        await bot.set_my_commands(COMMANDS)
        background = asyncio.create_task(background_loop(bot, sessionmaker, settings))
        log.info("Bot ishga tushdi")
        await dispatcher.start_polling(bot)
    finally:
        if background is not None:
            background.cancel()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
