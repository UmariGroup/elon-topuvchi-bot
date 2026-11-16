"""Qoida: bitta telefon raqam ko'p turli e'londa."""

from __future__ import annotations

from elon.rules.base import Finding

LIMIT = 3
HEAVY_LIMIT = 8


def phone_reuse(
    other_listings: int, *, limit: int = LIMIT, heavy_limit: int = HEAVY_LIMIT
) -> Finding | None:
    """`other_listings` — shu raqam bilan chiqqan BOSHQA (dublikat bo'lmagan) e'lonlar soni."""
    if other_listings < limit:
        return None
    heavy = other_listings >= heavy_limit
    return Finding(
        code="phone_reuse",
        penalty=25 if heavy else 15,
        reason=(
            f"Shu telefon raqam yana {other_listings} ta boshqa e'londa uchradi "
            "(vositachi bo'lishi mumkin)"
        ),
    )
