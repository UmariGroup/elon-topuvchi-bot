"""Collector servisi: kanallarni o'qish + parser konveyeri.

Ishga tushirish: `python -m elon.collector.main`
"""

from __future__ import annotations

import asyncio
import logging
import random

from sqlalchemy import select
from telethon import errors

from elon.collector.channels import load_channels, sync_channels
from elon.collector.service import ChannelUnavailable, disable_channel, join_next, poll_channel
from elon.collector.telegram import NotAuthorized, TelegramSource, sleep_flood
from elon.config import Settings, get_settings
from elon.db.models import Channel
from elon.db.session import SessionMaker, init_db, make_engine, make_sessionmaker
from elon.llm.client import AnthropicLLM, LLMClient
from elon.llm.pricing import price_for
from elon.logsetup import setup_logging
from elon.pipeline.ingest import PostData, store_post
from elon.pipeline.parse import process_pending
from elon.timeutil import utcnow

log = logging.getLogger("elon.collector")

JOIN_PAUSE_SECONDS = (180, 480)
PARSE_IDLE_SECONDS = 10
BUDGET_PAUSE_SECONDS = 600
SESSION_WAIT_SECONDS = 60


async def poll_loop(sessionmaker: SessionMaker, source: TelegramSource, settings: Settings) -> None:
    while True:
        async with sessionmaker() as session:
            channel_ids = (
                (
                    await session.execute(
                        select(Channel.id).where(Channel.enabled).order_by(Channel.id)
                    )
                )
                .scalars()
                .all()
            )
        for channel_id in channel_ids:
            async with sessionmaker() as session:
                channel = await session.get(Channel, channel_id)
                if channel is None:
                    continue
                # rollback'dan keyin ORM maydonlari o'qilmaydi, shuning uchun oldindan olamiz
                username = channel.username
                try:
                    stored = await poll_channel(
                        session, source, channel, utcnow(), backfill_days=settings.backfill_days
                    )
                    await session.commit()
                    if stored:
                        log.info("@%s: %s ta yangi post", username, stored)
                except errors.FloodWaitError as exc:
                    await session.rollback()
                    await sleep_flood(exc)
                except ChannelUnavailable as exc:
                    disable_channel(channel, str(exc))
                    await session.commit()
                    log.warning("@%s o'chirildi: %s", username, exc)
                except Exception as exc:
                    await session.rollback()
                    log.exception("@%s o'qishda xato: %s", username, type(exc).__name__)
            # Kanallar orasida tasodifiy pauza — limitga urilmaslik uchun
            await asyncio.sleep(random.uniform(2, 5))  # noqa: S311
        await asyncio.sleep(settings.poll_interval_seconds)


async def join_loop(sessionmaker: SessionMaker, source: TelegramSource, settings: Settings) -> None:
    """Kanallarga sekin a'zo bo'ladi: kuniga ko'pi bilan MAX_JOINS_PER_DAY, orada bir necha daqiqa."""
    while True:
        await asyncio.sleep(random.uniform(*JOIN_PAUSE_SECONDS))  # noqa: S311
        async with sessionmaker() as session:
            try:
                channel = await join_next(
                    session, source, utcnow(), max_per_day=settings.max_joins_per_day
                )
                await session.commit()
                if channel is not None and channel.joined_at is not None:
                    log.info("@%s kanaliga a'zo bo'lindi", channel.username)
            except errors.FloodWaitError as exc:
                # Urinish vaqti saqlanadi: shu kanal 3 kundan keyin qayta uriniladi
                await session.commit()
                await sleep_flood(exc)
            except Exception as exc:
                await session.commit()
                log.exception("A'zo bo'lishda xato: %s", type(exc).__name__)


async def parse_loop(sessionmaker: SessionMaker, llm: LLMClient, settings: Settings) -> None:
    while True:
        try:
            stats = await process_pending(sessionmaker, llm, settings)
        except Exception as exc:
            log.exception("Parser konveyerida xato: %s", type(exc).__name__)
            await asyncio.sleep(PARSE_IDLE_SECONDS)
            continue
        processed = stats.parsed + stats.duplicates + stats.skipped + stats.failed
        if processed:
            log.info(
                "Tahlil: %s yangi, %s dublikat, %s o'tkazib yuborildi, %s xato",
                stats.parsed,
                stats.duplicates,
                stats.skipped,
                stats.failed,
            )
        if stats.budget_stopped:
            await asyncio.sleep(BUDGET_PAUSE_SECONDS)
        elif not processed:
            await asyncio.sleep(PARSE_IDLE_SECONDS)


async def connect_telegram(settings: Settings) -> TelegramSource:
    """Telegram'ga ulanadi. Session hali yaratilmagan bo'lsa, yaratilguncha kutadi."""
    while True:
        source = TelegramSource(settings)
        try:
            await source.start()
            return source
        except NotAuthorized as exc:
            log.error("%s", exc)
            await source.client.disconnect()
            await asyncio.sleep(SESSION_WAIT_SECONDS)


async def run() -> None:
    setup_logging()
    settings = get_settings()
    price_for(settings.parser_model)  # noma'lum model bo'lsa darhol to'xtaydi
    engine = make_engine(settings.database_url.get_secret_value())
    await init_db(engine)
    sessionmaker = make_sessionmaker(engine)

    async with sessionmaker() as session:
        added = await sync_channels(session, load_channels(settings.channels_file))
        await session.commit()
    log.info("Kanallar ro'yxati sinxronlandi (yangi: %s)", added)

    source = await connect_telegram(settings)

    async def on_new_post(chat_id: int, post: PostData) -> None:
        async with sessionmaker() as session:
            channel = (
                await session.execute(
                    select(Channel).where(Channel.tg_id == chat_id, Channel.enabled)
                )
            ).scalar_one_or_none()
            if channel is None:
                return
            await store_post(session, channel, post, utcnow())
            await session.commit()

    source.on_new_post(on_new_post)
    llm = AnthropicLLM(settings.anthropic_api_key.get_secret_value())
    log.info("Collector ishga tushdi")
    await asyncio.gather(
        poll_loop(sessionmaker, source, settings),
        join_loop(sessionmaker, source, settings),
        parse_loop(sessionmaker, llm, settings),
        source.client.run_until_disconnected(),
    )


if __name__ == "__main__":
    asyncio.run(run())
