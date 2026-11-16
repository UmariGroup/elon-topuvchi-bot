"""Qoida: juda eski e'lon."""

from __future__ import annotations

from datetime import datetime

from elon.rules.base import Finding

WARN_DAYS = 14
OLD_DAYS = 30


def stale(
    posted_at: datetime, now: datetime, *, warn_days: int = WARN_DAYS, old_days: int = OLD_DAYS
) -> Finding | None:
    """`posted_at` — e'lon oxirgi marta ko'ringan sana (qayta joylansa yangilanadi)."""
    days = (now - posted_at).days
    if days < warn_days:
        return None
    old = days >= old_days
    return Finding(
        code="stale",
        penalty=35 if old else 15,
        reason=f"E'lon {days} kun oldin joylangan — hali bo'sh ekanini aniqlang",
    )
