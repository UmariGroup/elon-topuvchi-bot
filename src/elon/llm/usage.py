"""AI xarajatini bazaga yozish va kunlik limitni tekshirish."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.db.models import AdminEvent, AiCall
from elon.llm.pricing import TokenUsage, cost_micro_usd
from elon.timeutil import TASHKENT, tashkent_day_start


async def record_ai_call(
    session: AsyncSession,
    *,
    purpose: str,
    model: str,
    usage: TokenUsage,
    now: datetime,
    user_id: int | None = None,
    raw_post_id: int | None = None,
) -> AiCall:
    call = AiCall(
        created_at=now,
        purpose=purpose,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cost_micro_usd=cost_micro_usd(model, usage),
        user_id=user_id,
        raw_post_id=raw_post_id,
    )
    session.add(call)
    await session.flush()
    return call


async def spent_today_micro_usd(session: AsyncSession, now: datetime) -> int:
    """Bugun (Toshkent vaqti bilan) sarflangan jami AI xarajati."""
    result = await session.execute(
        select(func.coalesce(func.sum(AiCall.cost_micro_usd), 0)).where(
            AiCall.created_at >= tashkent_day_start(now)
        )
    )
    return int(result.scalar_one())


async def budget_exceeded(session: AsyncSession, budget_micro_usd: int, now: datetime) -> bool:
    return await spent_today_micro_usd(session, now) >= budget_micro_usd


async def queue_admin_event(
    session: AsyncSession, text: str, now: datetime, *, dedup_key: str | None = None
) -> bool:
    """Admin'ga xabar navbatga qo'yadi. `dedup_key` takrorlansa qo'shilmaydi."""
    if dedup_key is not None:
        existing = await session.execute(
            select(AdminEvent.id).where(AdminEvent.dedup_key == dedup_key)
        )
        if existing.first() is not None:
            return False
    session.add(AdminEvent(dedup_key=dedup_key, text=text, created_at=now))
    await session.flush()
    return True


async def notify_budget_exceeded(
    session: AsyncSession, budget_micro_usd: int, now: datetime
) -> bool:
    day = now.astimezone(TASHKENT).date().isoformat()
    spent = await spent_today_micro_usd(session, now)
    text = (
        "⚠️ Kunlik AI limiti tugadi.\n"
        f"Sarflandi: ${spent / 1_000_000:.2f} / limit ${budget_micro_usd / 1_000_000:.2f}.\n"
        "Yangi e'lonlarni tahlil qilish ertangi kungacha to'xtatildi. "
        "Limitni oshirish: .env dagi DAILY_AI_BUDGET_USD."
    )
    return await queue_admin_event(session, text, now, dedup_key=f"budget:{day}")
