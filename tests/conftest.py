from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from elon.config import Settings
from elon.db.base import Base
from elon.db.session import SessionMaker, make_sessionmaker, normalize_url
from elon.llm.client import ChatMessage, LLMResult, ToolSchema
from elon.llm.pricing import TokenUsage

#: 2026-11-13 12:00 Toshkent vaqti
NOW = datetime(2026, 11, 13, 7, 0, tzinfo=UTC)

Responder = Callable[[dict[str, Any]], dict[str, Any] | Exception]


class FakeLLM:
    """Claude o'rniga: navbatdagi javoblarni qaytaradi va chaqiruvlarni yozib boradi."""

    def __init__(self, responder: Responder | None = None, usage: TokenUsage | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.queue: list[dict[str, Any] | Exception] = []
        self.responder = responder
        self.usage = usage or TokenUsage(
            input_tokens=300, output_tokens=150, cache_read_tokens=1500
        )

    async def call_tool(
        self,
        *,
        model: str,
        system: str,
        messages: list[ChatMessage],
        tool: ToolSchema,
        max_tokens: int,
    ) -> LLMResult:
        call = {"model": model, "system": system, "messages": messages, "tool": tool}
        self.calls.append(call)
        if self.queue:
            item = self.queue.pop(0)
        elif self.responder is not None:
            item = self.responder(call)
        else:
            raise AssertionError("FakeLLM: kutilmagan chaqiruv")
        if isinstance(item, Exception):
            raise item
        return LLMResult(data=item, usage=self.usage)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "telegram_bot_token": "123456:TEST-token",
        "tg_api_id": 1,
        "tg_api_hash": "test-api-hash",
        "anthropic_api_key": "test-key",
        "database_url": "sqlite+aiosqlite://",
        "admin_ids": [999],
        "trial_days": 7,
        "daily_ai_budget_usd": Decimal("3"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Standart — xotiradagi SQLite. TEST_DATABASE_URL berilsa haqiqiy PostgreSQL'da ishlaydi."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = create_async_engine(normalize_url(url))
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> SessionMaker:
    return make_sessionmaker(engine)
