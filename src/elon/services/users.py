"""Foydalanuvchi: ro'yxat, sinov muddati, faollashtirish, ma'lumotni o'chirish."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from elon.db.models import (
    AiCall,
    Conversation,
    Feedback,
    Notification,
    SearchLog,
    User,
    Watch,
)
from elon.llm.usage import queue_admin_event


class Access(StrEnum):
    TRIAL = "trial"
    PAID = "paid"
    EXPIRED = "expired"


def access_of(user: User, now: datetime) -> Access:
    if user.paid_until is not None and user.paid_until > now:
        return Access.PAID
    if user.trial_ends_at > now:
        return Access.TRIAL
    return Access.EXPIRED


def access_until(user: User, now: datetime) -> datetime | None:
    state = access_of(user, now)
    if state is Access.PAID:
        return user.paid_until
    if state is Access.TRIAL:
        return user.trial_ends_at
    return None


async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def register(
    session: AsyncSession, *, tg_id: int, phone: str, now: datetime, trial_days: int
) -> tuple[User, bool]:
    """Ro'yxatdan o'tkazadi. (foydalanuvchi, yangi_yaratildimi). Qayta /start sinovni uzaytirmaydi."""
    existing = await get_user(session, tg_id)
    if existing is not None:
        return existing, False
    user = User(
        tg_id=tg_id,
        phone=phone,
        registered_at=now,
        trial_ends_at=now + timedelta(days=trial_days),
    )
    session.add(user)
    await session.flush()
    return user, True


async def activate(session: AsyncSession, *, tg_id: int, days: int, now: datetime) -> User | None:
    """Admin qo'lda faollashtiradi. Amaldagi obuna ustiga qo'shiladi."""
    user = await get_user(session, tg_id)
    if user is None:
        return None
    base = user.paid_until if user.paid_until is not None and user.paid_until > now else now
    user.paid_until = base + timedelta(days=days)
    user.expiry_notified_at = None
    return user


async def delete_user(session: AsyncSession, tg_id: int) -> bool:
    """/delete_me: foydalanuvchining barcha shaxsiy ma'lumotini o'chiradi."""
    user = await get_user(session, tg_id)
    if user is None:
        return False
    for model in (Conversation, SearchLog, Watch, Notification, Feedback):
        await session.execute(delete(model).where(model.user_id == user.id))
    # AI xarajat yozuvlarida matn yo'q; hisob-kitob buzilmasligi uchun faqat bog'lanish uziladi
    await session.execute(update(AiCall).where(AiCall.user_id == user.id).values(user_id=None))
    await session.delete(user)
    await session.flush()
    return True


async def expire_tick(session: AsyncSession, now: datetime) -> list[User]:
    """Muddati tugagan, hali xabar berilmagan foydalanuvchilarni topib belgilaydi.

    Admin'ga bildirishnoma navbatga qo'yiladi; foydalanuvchiga xabarni chaqiruvchi yuboradi.
    """
    result = await session.execute(
        select(User).where(
            User.trial_ends_at <= now,
            or_(User.paid_until.is_(None), User.paid_until <= now),
            User.expiry_notified_at.is_(None),
        )
    )
    expired = list(result.scalars())
    for user in expired:
        user.expiry_notified_at = now
        kind = "obunasi" if user.paid_until is not None else "bepul sinovi"
        await queue_admin_event(
            session,
            f"⏰ Foydalanuvchining {kind} tugadi.\n"
            f"ID: {user.tg_id}\n"
            f"Faollashtirish: /activate {user.tg_id} 7",
            now,
        )
    return expired
