"""Admin uchun /stats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.db.models import AiCall, Feedback, Listing, RawPost, SearchLog, User, Watch
from elon.timeutil import tashkent_day_start


@dataclass(frozen=True)
class Stats:
    registered: int
    active: int
    trial_ended: int
    trial_ended_paid: int
    searches_total: int
    searches_today: int
    watches_active: int
    likes: int
    dislikes: int
    ai_cost_today_usd: float
    ai_cost_total_usd: float
    ai_cache_read_share: float
    posts_total: int
    posts_pending: int
    listings_unique: int

    def format(self) -> str:
        votes = self.likes + self.dislikes
        ratio = f"{self.likes / votes:.0%} ijobiy" if votes else "hali baho yo'q"
        return "\n".join(
            [
                "📊 Statistika",
                f"Ro'yxatdan o'tganlar: {self.registered}",
                f"Faol (sinov yoki obuna amalda): {self.active}",
                f"Sinovi tugaganlar: {self.trial_ended} (shundan obuna olgan: {self.trial_ended_paid})",
                f"So'rovlar: jami {self.searches_total}, bugun {self.searches_today}",
                f"Faol kuzatuvlar: {self.watches_active}",
                f"👍 {self.likes} / 👎 {self.dislikes} — {ratio}",
                f"AI xarajati: bugun ${self.ai_cost_today_usd:.2f}, jami ${self.ai_cost_total_usd:.2f}",
                f"Keshdan o'qilgan prompt ulushi: {self.ai_cache_read_share:.0%}",
                f"Postlar: jami {self.posts_total}, navbatda {self.posts_pending}",
                f"Noyob e'lonlar: {self.listings_unique}",
            ]
        )


async def _scalar(session: AsyncSession, query: object) -> int:
    result = await session.execute(query)  # type: ignore[call-overload]
    return int(result.scalar_one() or 0)


async def collect_stats(session: AsyncSession, now: datetime) -> Stats:
    day = tashkent_day_start(now)
    count = func.count()
    has_access = or_(User.trial_ends_at > now, User.paid_until > now)

    prompt_tokens = await _scalar(
        session,
        select(
            func.coalesce(
                func.sum(
                    AiCall.input_tokens + AiCall.cache_write_tokens + AiCall.cache_read_tokens
                ),
                0,
            )
        ),
    )
    cache_read = await _scalar(
        session, select(func.coalesce(func.sum(AiCall.cache_read_tokens), 0))
    )

    return Stats(
        registered=await _scalar(session, select(count).select_from(User)),
        active=await _scalar(session, select(count).select_from(User).where(has_access)),
        trial_ended=await _scalar(
            session, select(count).select_from(User).where(User.trial_ends_at <= now)
        ),
        trial_ended_paid=await _scalar(
            session,
            select(count)
            .select_from(User)
            .where(User.trial_ends_at <= now, User.paid_until.is_not(None)),
        ),
        searches_total=await _scalar(session, select(count).select_from(SearchLog)),
        searches_today=await _scalar(
            session, select(count).select_from(SearchLog).where(SearchLog.created_at >= day)
        ),
        watches_active=await _scalar(session, select(count).select_from(Watch).where(Watch.active)),
        likes=await _scalar(session, select(count).select_from(Feedback).where(Feedback.value > 0)),
        dislikes=await _scalar(
            session, select(count).select_from(Feedback).where(Feedback.value < 0)
        ),
        ai_cost_today_usd=await _scalar(
            session,
            select(func.coalesce(func.sum(AiCall.cost_micro_usd), 0)).where(
                AiCall.created_at >= day
            ),
        )
        / 1_000_000,
        ai_cost_total_usd=await _scalar(
            session, select(func.coalesce(func.sum(AiCall.cost_micro_usd), 0))
        )
        / 1_000_000,
        ai_cache_read_share=(cache_read / prompt_tokens) if prompt_tokens else 0.0,
        posts_total=await _scalar(session, select(count).select_from(RawPost)),
        posts_pending=await _scalar(
            session, select(count).select_from(RawPost).where(RawPost.status == "new")
        ),
        listings_unique=await _scalar(
            session, select(count).select_from(Listing).where(Listing.duplicate_of_id.is_(None))
        ),
    )
