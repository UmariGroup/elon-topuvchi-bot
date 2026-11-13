"""Qoida: narx bozor medianasidan juda past."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median

from elon.rules.base import Finding

THRESHOLD = 0.35
SEVERE_THRESHOLD = 0.50
MIN_SAMPLES = 5


def market_median(prices: Sequence[int], *, min_samples: int = MIN_SAMPLES) -> float | None:
    """Segment medianasi. Namuna kam bo'lsa `None` (qoida ishlamaydi)."""
    if len(prices) < min_samples:
        return None
    return float(median(prices))


def below_market(
    price_usd: int | None,
    median_usd: float | None,
    *,
    threshold: float = THRESHOLD,
    severe_threshold: float = SEVERE_THRESHOLD,
) -> Finding | None:
    if price_usd is None or median_usd is None or median_usd <= 0:
        return None
    discount = 1 - price_usd / median_usd
    if discount < threshold:
        return None
    percent = round(discount * 100)
    severe = discount >= severe_threshold
    return Finding(
        code="below_market",
        penalty=50 if severe else 35,
        reason=(
            f"Narx shu tuman va xona soni bo'yicha o'rtacha narxdan {percent}% past "
            f"(o'rtacha ≈ {round(median_usd)}$)"
        ),
    )
