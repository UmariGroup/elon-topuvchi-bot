"""Telefon raqamlarni ajratish, me'yorlash va xeshlash (pure)."""

from __future__ import annotations

import hashlib
import hmac
import re

_CANDIDATE = re.compile(r"(?<![\w.])\+?\d[\d\s\-()]{7,16}\d(?!\w)")

#: O'zbekiston mobil va shahar kodlari (operator prefikslari)
_VALID_PREFIXES = {
    "20", "33", "50", "55", "61", "62", "65", "66", "67", "69", "70", "71", "72", "73", "74",
    "75", "76", "77", "78", "79", "87", "88", "90", "91", "93", "94", "95", "97", "98", "99",
}  # fmt: skip


def normalize_phone(raw: str | None) -> str | None:
    """Har xil yozilgan raqamni `998XXXXXXXXX` ko'rinishiga keltiradi; yaroqsiz bo'lsa `None`."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) != 12 or not digits.startswith("998"):
        return None
    if digits[3:5] not in _VALID_PREFIXES:
        return None
    return digits


def extract_phones(text: str) -> list[str]:
    """Matndagi barcha yaroqli telefon raqamlar (me'yorlangan, takrorsiz, tartib saqlanadi)."""
    found: list[str] = []
    for match in _CANDIDATE.finditer(text):
        phone = normalize_phone(match.group(0))
        if phone and phone not in found:
            found.append(phone)
    return found


def hash_phone(phone: str, key: bytes) -> str:
    """Qaytarib bo'lmaydigan iz. Kalitsiz xesh 9 xonali raqam uchun oson teriladi, shuning uchun HMAC."""
    return hmac.new(key, phone.encode(), hashlib.sha256).hexdigest()
