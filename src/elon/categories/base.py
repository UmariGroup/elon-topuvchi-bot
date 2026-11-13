"""Toifa interfeysi.

Collector va parser konveyeri toifani bilmaydi: ular faqat shu interfeys bilan ishlaydi.
Yangi toifa (texnika, avto, ish e'lonlari) qo'shish uchun `Category` ni amalga oshirib,
`elon.categories.REGISTRY` ga yozish kifoya.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from elon.llm.client import ToolSchema


class Extracted(BaseModel):
    """Parser natijasi: barcha toifalar uchun umumiy maydonlar + toifaga xos `attrs`."""

    location: str | None = None
    #: bozor medianasi shu kalit bo'yicha guruhlanadi
    segment: str | None = None
    price_usd: int | None = None
    price_original: int | None = None
    currency: str | None = None
    summary: str
    is_agent: bool | None = None
    #: me'yorlangan telefon (bazaga faqat xeshi yoziladi)
    phone: str | None = None
    deposit_requested: bool | None = None
    prepay_before_viewing: bool | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class Category(ABC):
    name: str
    parser_system_prompt: str
    parser_tool: ToolSchema

    @abstractmethod
    def prefilter(self, text: str) -> str | None:
        """AI'ga yuborishdan oldin arzon tekshiruv. O'tkazib yuborish sababi yoki `None`."""

    @abstractmethod
    def build(self, data: dict[str, Any], *, text: str, usd_uzs_rate: int) -> Extracted | None:
        """Model javobini `Extracted` ga aylantiradi. Bu toifa e'loni bo'lmasa `None`."""
