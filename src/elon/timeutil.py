from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

#: O'zbekistonda yozgi vaqt yo'q, shuning uchun qat'iy UTC+5 yetarli.
TASHKENT = timezone(timedelta(hours=5), name="Asia/Tashkent")


def utcnow() -> datetime:
    return datetime.now(UTC)


def tashkent_day_start(now: datetime) -> datetime:
    """Toshkent vaqti bilan bugungi kun boshlanishi (UTC ko'rinishida)."""
    local = now.astimezone(TASHKENT)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC)
