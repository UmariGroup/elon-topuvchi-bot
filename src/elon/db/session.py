from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from elon.db import models  # noqa: F401  (jadvallar Base.metadata'ga yozilishi uchun)
from elon.db.base import Base

log = logging.getLogger(__name__)

SessionMaker = async_sessionmaker[AsyncSession]


def normalize_url(url: str) -> str:
    """`postgresql://` ko'rinishidagi manzilni asyncpg drayveriga moslaydi."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(normalize_url(database_url), pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> SessionMaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine, *, retries: int = 30, delay: float = 2.0) -> None:
    """Jadvallarni yaratadi. Baza hali ko'tarilmagan bo'lsa kutadi."""
    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                if conn.dialect.name == "postgresql":
                    # bot va collector bir vaqtda ishga tushsa jadval yaratishda to'qnashmasin
                    await conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
                await conn.run_sync(Base.metadata.create_all)
            return
        except (OperationalError, OSError) as exc:
            if attempt == retries:
                raise
            log.warning("Baza hali tayyor emas (%s), kutyapman...", type(exc).__name__)
            await asyncio.sleep(delay)
