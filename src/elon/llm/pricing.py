"""Model narxlari va chaqiruv narxini hisoblash (pure funksiyalar).

Narxlar: https://platform.claude.com/docs/en/about-claude/pricing (2026-11-13 holatiga).
Narx o'zgarsa faqat shu faylni yangilash kerak.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens


@dataclass(frozen=True)
class ModelPrice:
    """1 million token uchun USD."""

    input: Decimal
    cache_write: Decimal
    cache_read: Decimal
    output: Decimal
    #: prompt shu chegaradan uzun bo'lsa barcha narxlar `long_multiplier` ga ko'payadi
    long_prompt_threshold: int | None = None
    long_multiplier: Decimal = Decimal(1)


PRICES: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(
        input=Decimal("0.10"),
        cache_write=Decimal("0.125"),
        cache_read=Decimal("0.01"),
        output=Decimal("0.50"),
        long_prompt_threshold=100_000,
        long_multiplier=Decimal(5),
    ),
    "claude-sonnet-5-5": ModelPrice(
        input=Decimal("2"),
        cache_write=Decimal("2.50"),
        cache_read=Decimal("0.10"),
        output=Decimal("10"),
    ),
}


class UnknownModelError(KeyError):
    pass


def price_for(model: str) -> ModelPrice:
    try:
        return PRICES[model]
    except KeyError:
        raise UnknownModelError(
            f"'{model}' modeli uchun narx kiritilmagan — src/elon/llm/pricing.py ga qo'shing"
        ) from None


def cost_micro_usd(model: str, usage: TokenUsage) -> int:
    """Chaqiruv narxi mikro-dollarda (yuqoriga yaxlitlanadi, limit kam hisoblanmasin)."""
    price = price_for(model)
    multiplier = Decimal(1)
    if (
        price.long_prompt_threshold is not None
        and usage.prompt_tokens > price.long_prompt_threshold
    ):
        multiplier = price.long_multiplier
    # (token * USD/MTok) = mikro-dollar
    total = (
        usage.input_tokens * price.input
        + usage.cache_write_tokens * price.cache_write
        + usage.cache_read_tokens * price.cache_read
        + usage.output_tokens * price.output
    ) * multiplier
    return int(total.to_integral_value(rounding=ROUND_CEILING))
