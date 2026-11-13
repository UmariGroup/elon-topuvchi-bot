"""Dublikat e'lonlarni aniqlash: matn o'xshashligi + telefon + narx (pure)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_URL = re.compile(r"https?://\S+|t\.me/\S+|@\w+")
_NON_WORD = re.compile(r"[^\w']+", re.UNICODE)

SIM_SAME_TEXT = 0.85
SIM_WITH_PHONE_AND_PRICE = 0.35


def normalize_text(text: str) -> str:
    text = _URL.sub(" ", text.lower())
    text = text.replace("‘", "'").replace("’", "'").replace("ʻ", "'").replace("`", "'")
    return _NON_WORD.sub(" ", text).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


def shingles(text: str, size: int = 3) -> frozenset[str]:
    words = normalize_text(text).split()
    if len(words) <= size:
        return frozenset(words)
    return frozenset(" ".join(words[i : i + size]) for i in range(len(words) - size + 1))


def similarity(a: str, b: str) -> float:
    """So'z uchliklari bo'yicha Jaccard o'xshashligi, 0..1."""
    left, right = shingles(a), shingles(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True)
class DedupKey:
    text: str
    phone_hash: str | None
    price_usd: int | None
    segment: str | None


def is_duplicate(new: DedupKey, old: DedupKey) -> bool:
    sim = similarity(new.text, old.text)
    if sim >= SIM_SAME_TEXT:
        return True
    same_phone = new.phone_hash is not None and new.phone_hash == old.phone_hash
    same_price = new.price_usd is not None and new.price_usd == old.price_usd
    same_segment = new.segment is not None and new.segment == old.segment
    # Bitta odam bir xil narxda, bir xil tuman/xonada qayta joylagan — matn biroz o'zgargan bo'lsa ham
    return same_phone and same_price and (sim >= SIM_WITH_PHONE_AND_PRICE or same_segment)
