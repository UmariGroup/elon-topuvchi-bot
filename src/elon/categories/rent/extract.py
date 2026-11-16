"""Ijara toifasi: model javobini tekshirib, me'yorlangan `Extracted` ga aylantirish."""

from __future__ import annotations

import re
from typing import Any

from elon.categories.base import Category, Extracted
from elon.categories.rent.districts import DISTRICTS
from elon.categories.rent.prompts import FOR_WHOM, PARSER_SYSTEM, PARSER_TOOL, RENTAL_TYPES
from elon.pipeline.phones import extract_phones, normalize_phone

MIN_TEXT_LENGTH = 40
MIN_PRICE_USD = 30
MAX_PRICE_USD = 20_000

_RENT_HINT = re.compile(
    r"ijara|ижара|arenda|аренд|сда[её]тся|сдам|сдаю|beriladi|берилади|kvartira|квартира|xona|хона"
    r"|комнат",
    re.IGNORECASE,
)


def normalize_price(
    amount: float | int | None, currency: str | None, usd_uzs_rate: int
) -> tuple[int | None, int | None, str | None]:
    """(price_usd, price_original, currency). Aqlga sig'maydigan narx `None` bo'ladi."""
    if amount is None or amount <= 0 or currency not in ("USD", "UZS"):
        return None, None, None
    original = round(amount)
    usd = round(amount / usd_uzs_rate) if currency == "UZS" else original
    if not MIN_PRICE_USD <= usd <= MAX_PRICE_USD:
        return None, None, None
    return usd, original, currency


def _as_int(value: Any, *, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = round(value)
    return number if low <= number <= high else None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:limit] or None


def segment_key(district: str | None, rooms: int | None, rental_type: str | None) -> str | None:
    if district is None or rooms is None or rental_type != "kvartira":
        return None
    return f"{district}|{rooms}"


class RentCategory(Category):
    name = "rent"
    parser_system_prompt = PARSER_SYSTEM
    parser_tool = PARSER_TOOL

    def prefilter(self, text: str) -> str | None:
        if len(text.strip()) < MIN_TEXT_LENGTH:
            return "too_short"
        if not _RENT_HINT.search(text):
            return "no_rent_keywords"
        return None

    def build(self, data: dict[str, Any], *, text: str, usd_uzs_rate: int) -> Extracted | None:
        if data.get("is_listing") is not True:
            return None

        district = data.get("district")
        if district not in DISTRICTS:
            district = None
        rental_type = data.get("rental_type")
        if rental_type not in RENTAL_TYPES:
            rental_type = None
        rooms = _as_int(data.get("rooms"), low=1, high=10)
        floor = _as_int(data.get("floor"), low=0, high=60)
        floors_total = _as_int(data.get("floors_total"), low=1, high=60)
        if floor is not None and floors_total is not None and floor > floors_total:
            floor, floors_total = None, None
        area = data.get("area_m2")
        area_m2 = (
            round(float(area), 1)
            if isinstance(area, int | float) and not isinstance(area, bool) and 8 <= area <= 500
            else None
        )
        price_usd, price_original, currency = normalize_price(
            data.get("price_amount"), data.get("price_currency"), usd_uzs_rate
        )
        raw_for_whom = data.get("for_whom")
        for_whom = (
            [item for item in raw_for_whom if item in FOR_WHOM]
            if isinstance(raw_for_whom, list)
            else []
        )
        poster = data.get("poster")
        is_agent = (
            {"egasi": False, "vositachi": True}.get(poster) if isinstance(poster, str) else None
        )

        # Telefon: regex ishonchliroq, model javobi faqat zaxira
        phones = extract_phones(text)
        phone = phones[0] if phones else normalize_phone(_as_text(data.get("phone"), 40))

        return Extracted(
            location=district,
            segment=segment_key(district, rooms, rental_type),
            price_usd=price_usd,
            price_original=price_original,
            currency=currency,
            summary=_as_text(data.get("summary_uz"), 400) or "Kvartira ijarasi",
            is_agent=is_agent,
            phone=phone,
            deposit_requested=_as_bool(data.get("deposit_requested")),
            prepay_before_viewing=_as_bool(data.get("prepay_before_viewing")),
            attrs={
                "landmark": _as_text(data.get("landmark"), 160),
                "rental_type": rental_type,
                "rooms": rooms,
                "floor": floor,
                "floors_total": floors_total,
                "area_m2": area_m2,
                "furnished": _as_bool(data.get("furnished")),
                "for_whom": for_whom,
            },
        )


RENT = RentCategory()
