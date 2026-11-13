"""Barcha qoidalarni birlashtirib 0–100 ishonch ballini hisoblaydi (pure)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from elon.rules.age import stale
from elon.rules.base import Finding
from elon.rules.phone import phone_reuse
from elon.rules.photos import photos
from elon.rules.prepayment import prepayment
from elon.rules.price import below_market


@dataclass(frozen=True)
class RuleInput:
    """Qoidalar uchun kerakli hamma narsa. Bazadan yig'iladi, qoidalar bazaga tegmaydi."""

    price_usd: int | None
    median_usd: float | None
    deposit_requested: bool | None
    prepay_before_viewing: bool | None
    text: str
    other_listings_with_phone: int
    has_photo: bool
    photo_reused_elsewhere: int
    last_seen_at: datetime
    now: datetime


@dataclass(frozen=True)
class Trust:
    score: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [finding.reason for finding in self.findings]


def trust_score(findings: Iterable[Finding]) -> int:
    total = sum(finding.penalty for finding in findings)
    return max(0, min(100, 100 - total))


def evaluate(data: RuleInput) -> Trust:
    candidates = [
        below_market(data.price_usd, data.median_usd),
        prepayment(
            deposit_requested=data.deposit_requested,
            prepay_before_viewing=data.prepay_before_viewing,
            text=data.text,
        ),
        phone_reuse(data.other_listings_with_phone),
        photos(has_photo=data.has_photo, reused_elsewhere=data.photo_reused_elsewhere),
        stale(data.last_seen_at, data.now),
    ]
    findings = sorted(
        (finding for finding in candidates if finding is not None),
        key=lambda finding: finding.penalty,
        reverse=True,
    )
    return Trust(score=trust_score(findings), findings=findings)
