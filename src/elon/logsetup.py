"""Log sozlamasi. Telefon raqamlar logga tushmasligi uchun himoya filtri bor."""

from __future__ import annotations

import logging
import re

_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


class RedactPhones(logging.Filter):
    """Xabar ichida telefon raqamga o'xshash ketma-ketlik bo'lsa, yashiradi."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _PHONE_RE.sub(_mask, message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def _mask(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    # Telegram ID va xabar ID'lari ham raqam, ularni yashirmaslik kerak:
    # 998 bilan boshlanuvchi 12 xonali yoki ajratgichlar bilan yozilgan 9 xonali raqamgina telefon.
    formatted = raw != digits
    if (len(digits) == 12 and digits.startswith("998")) or (len(digits) == 9 and formatted):
        return "<telefon>"
    return raw


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactPhones())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # Telethon DEBUG darajasida xabar matnlarini chiqaradi — hech qachon yoqilmasin
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
