"""Toshkent shahri tumanlari (kanonik kalit -> ko'rsatiladigan nom)."""

from __future__ import annotations

DISTRICTS: dict[str, str] = {
    "bektemir": "Bektemir",
    "chilonzor": "Chilonzor",
    "mirobod": "Mirobod",
    "mirzo_ulugbek": "Mirzo Ulug'bek",
    "olmazor": "Olmazor",
    "sergeli": "Sergeli",
    "shayxontohur": "Shayxontohur",
    "uchtepa": "Uchtepa",
    "yakkasaroy": "Yakkasaroy",
    "yangihayot": "Yangihayot",
    "yashnobod": "Yashnobod",
    "yunusobod": "Yunusobod",
}

DISTRICT_KEYS: list[str] = list(DISTRICTS)


def district_name(key: str | None) -> str | None:
    if key is None:
        return None
    return DISTRICTS.get(key, key)
