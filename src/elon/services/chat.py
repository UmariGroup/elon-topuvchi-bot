"""Suhbat orqali qidiruv filtrini aniqlash (claude-sonnet-5-5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.categories.rent.filter import RentFilter
from elon.categories.rent.prompts import CHAT_SYSTEM, CHAT_TOOL
from elon.config import Settings
from elon.db.models import AiCall, Conversation, User
from elon.llm.client import ChatMessage, LLMClient
from elon.llm.usage import record_ai_call
from elon.timeutil import tashkent_day_start

MAX_HISTORY_MESSAGES = 12
MAX_USER_TEXT = 1000
FALLBACK_MESSAGE = "Tushunmadim, iltimos boshqacharoq yozib ko'ring."


class DailyLimitReached(Exception):
    pass


@dataclass(frozen=True)
class ChatReply:
    message: str
    ready: bool
    filter: RentFilter


async def get_conversation(session: AsyncSession, user: User, now: datetime) -> Conversation:
    result = await session.execute(select(Conversation).where(Conversation.user_id == user.id))
    conversation = result.scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(
            user_id=user.id, state="collecting", messages=[], filter=None, updated_at=now
        )
        session.add(conversation)
        await session.flush()
    return conversation


def current_filter(conversation: Conversation) -> RentFilter:
    try:
        return RentFilter.model_validate(conversation.filter or {})
    except ValidationError:
        return RentFilter()


async def messages_today(session: AsyncSession, user: User, now: datetime) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(AiCall)
        .where(
            AiCall.user_id == user.id,
            AiCall.purpose == "chat",
            AiCall.created_at >= tashkent_day_start(now),
        )
    )
    return int(result.scalar_one())


async def handle_message(
    session: AsyncSession,
    llm: LLMClient,
    settings: Settings,
    user: User,
    text: str,
    now: datetime,
) -> ChatReply:
    if await messages_today(session, user, now) >= settings.user_daily_message_limit:
        raise DailyLimitReached

    conversation = await get_conversation(session, user, now)
    previous = current_filter(conversation)
    history: list[ChatMessage] = list(conversation.messages)[-MAX_HISTORY_MESSAGES:]
    # Tarix "user" xabari bilan boshlanishi shart
    while history and history[0]["role"] != "user":
        history.pop(0)
    text = text.strip()[:MAX_USER_TEXT]
    wrapped = (
        f"<kurs>1 USD = {settings.usd_uzs_rate} so'm</kurs>\n"
        f"<joriy_filtr>{json.dumps(previous.model_dump(), ensure_ascii=False)}</joriy_filtr>\n"
        f"<xabar>{text}</xabar>"
    )
    result = await llm.call_tool(
        model=settings.chat_model,
        system=CHAT_SYSTEM,
        messages=[*history, {"role": "user", "content": wrapped}],
        tool=CHAT_TOOL,
        max_tokens=600,
    )
    await record_ai_call(
        session,
        purpose="chat",
        model=settings.chat_model,
        usage=result.usage,
        now=now,
        user_id=user.id,
    )

    raw_message = result.data.get("message")
    message = raw_message.strip() if isinstance(raw_message, str) else ""
    try:
        new_filter = RentFilter.model_validate(result.data.get("filter") or {})
        ready = result.data.get("ready") is True
    except ValidationError:
        new_filter, ready = previous, False
    if not message:
        message = FALLBACK_MESSAGE

    conversation.messages = [
        *history,
        {"role": "user", "content": text},
        {"role": "assistant", "content": message},
    ][-MAX_HISTORY_MESSAGES:]
    conversation.filter = new_filter.model_dump()
    conversation.state = "confirm" if ready else "collecting"
    conversation.updated_at = now
    return ChatReply(message=message, ready=ready, filter=new_filter)
