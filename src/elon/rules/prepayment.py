"""Qoida: oldindan to'lov / zaklad so'rash.

Ikki daraja:
- ko'rishdan oldin pul so'rash (firibgarlikning eng kuchli belgisi) — katta jarima;
- oddiy depozit/zaklad — kichik jarima (Toshkentda halol uy egalari ham so'raydi).

LLM matndan belgilarni topadi (`True`/`False`/`None`). LLM ishonchsiz (`None`) bo'lsa,
kalit so'zlar bo'yicha zaxira tekshiruv ishlaydi.
"""

from __future__ import annotations

import re

from elon.rules.base import Finding

_DEPOSIT = re.compile(
    r"zaklad|заклад|zalog|залог|depozit|депозит|oldindan\s+to['‘’`ʻ]?lov|олдиндан\s+тўлов"
    r"|predoplat|предоплат|предаплат",
    re.IGNORECASE,
)
_NEGATION_BEFORE = re.compile(
    r"(?:\bbez|\bбез|\bнет|\bno)\s+(?:\w+\s+(?:и|va|,)\s+)?$", re.IGNORECASE
)
_NEGATION_AFTER = re.compile(
    r"^\w*(?:siz\b|сиз\b)|^\w*\s+(?:yo['‘’`ʻ]?q|йўқ|йук|kerak\s+emas|керак\s+эмас|olinmaydi"
    r"|олинмайди|не\s+нужн|не\s+требу|so['‘’`ʻ]?ralmaydi)",
    re.IGNORECASE,
)
_BEFORE_VIEWING = re.compile(
    r"ko['‘’`ʻ]?r(?:ish|sat)\w*\s+oldin\w*\s+(?:\S+\s+){0,3}(?:pul|to['‘’`ʻ]?lov|o['‘’`ʻ]?tkaz)"
    r"|ko['‘’`ʻ]?rmasdan\s+(?:\S+\s+){0,3}(?:pul|to['‘’`ʻ]?lov)"
    r"|bron\w*\s+(?:\S+\s+){0,3}(?:pul|to['‘’`ʻ]?lov)\w*\s+(?:\S+\s+){0,2}(?:o['‘’`ʻ]?tkaz|tashla|yubor)"
    r"|karta\w*\s+(?:\S+\s+){0,3}(?:tashla|o['‘’`ʻ]?tkaz)\w*"
    r"|до\s+просмотра"
    r"|перев(?:од|ед)\w*\s+(?:\S+\s+){0,3}(?:на\s+карт|брон)"
    r"|брон\w*\s+(?:\S+\s+){0,3}(?:перев|оплат)",
    re.IGNORECASE,
)


def mentions_deposit(text: str) -> bool:
    """Matnda depozit/zaklad so'ralganmi (inkor shakllari — "depozitsiz", "без залога" — hisobga olinadi)."""
    for match in _DEPOSIT.finditer(text):
        before = text[max(0, match.start() - 30) : match.start()]
        after = text[match.start() : match.end() + 25]
        if _NEGATION_BEFORE.search(before) or _NEGATION_AFTER.search(after):
            continue
        return True
    return False


def mentions_prepay_before_viewing(text: str) -> bool:
    return _BEFORE_VIEWING.search(text) is not None


def prepayment(
    *,
    deposit_requested: bool | None,
    prepay_before_viewing: bool | None,
    text: str = "",
) -> Finding | None:
    before_viewing = (
        prepay_before_viewing
        if prepay_before_viewing is not None
        else mentions_prepay_before_viewing(text)
    )
    if before_viewing:
        return Finding(
            code="prepay_before_viewing",
            penalty=45,
            reason="Uyni ko'rishdan oldin pul o'tkazish so'ralgan — firibgarlik belgisi",
        )
    deposit = deposit_requested if deposit_requested is not None else mentions_deposit(text)
    if deposit:
        return Finding(
            code="deposit",
            penalty=10,
            reason="Oldindan to'lov yoki zaklad so'ralgan — pulni faqat uyni ko'rib, shartnoma bilan bering",
        )
    return None
