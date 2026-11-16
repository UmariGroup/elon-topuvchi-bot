"""Xavfsizlik qoidalari: har biri uchun ijobiy va salbiy holat."""

from __future__ import annotations

from datetime import timedelta

import pytest

from elon.rules import (
    Finding,
    RuleInput,
    below_market,
    evaluate,
    market_median,
    phone_reuse,
    photos,
    prepayment,
    stale,
    trust_score,
)
from elon.rules.prepayment import mentions_deposit, mentions_prepay_before_viewing
from tests.conftest import NOW

# ------------------------------------------------------------ narx


def test_below_market_flags_price_35_percent_under_median() -> None:
    finding = below_market(250, 400.0)  # 37.5% past
    assert finding is not None
    assert finding.code == "below_market"
    assert finding.penalty == 35
    assert "38%" in finding.reason


def test_below_market_severe_when_half_price() -> None:
    finding = below_market(180, 400.0)
    assert finding is not None and finding.penalty == 50


def test_below_market_exact_threshold_is_flagged() -> None:
    assert below_market(260, 400.0) is not None  # aynan 35%


def test_below_market_ignores_normal_price() -> None:
    assert below_market(300, 400.0) is None  # 25% past — oddiy chegirma
    assert below_market(450, 400.0) is None


def test_below_market_needs_price_and_median() -> None:
    assert below_market(None, 400.0) is None
    assert below_market(100, None) is None


def test_market_median_requires_enough_samples() -> None:
    assert market_median([300, 350, 400, 450]) is None
    assert market_median([300, 350, 400, 450, 500]) == 400.0


# ------------------------------------------------------------ oldindan to'lov


def test_prepayment_before_viewing_is_heavy() -> None:
    finding = prepayment(deposit_requested=True, prepay_before_viewing=True)
    assert finding is not None
    assert finding.code == "prepay_before_viewing"
    assert finding.penalty == 45


def test_prepayment_plain_deposit_is_light() -> None:
    finding = prepayment(deposit_requested=True, prepay_before_viewing=False)
    assert finding is not None
    assert finding.code == "deposit"
    assert finding.penalty == 10


def test_prepayment_none_when_not_requested() -> None:
    assert prepayment(deposit_requested=False, prepay_before_viewing=False) is None
    assert (
        prepayment(deposit_requested=None, prepay_before_viewing=None, text="Toza kvartira") is None
    )


def test_prepayment_llm_answer_wins_over_keywords() -> None:
    # Model "depozit so'ralmagan" degan — matndagi so'z (masalan "depozitsiz") hisobga olinmaydi
    assert (
        prepayment(deposit_requested=False, prepay_before_viewing=False, text="zaklad 1 oylik")
        is None
    )


@pytest.mark.parametrize(
    "text",
    [
        "Narxi 400$, zaklad 1 oylik",
        "Depozit 300$ olinadi",
        "Oldindan to'lov 2 oylik",
        "Оплата: предоплата за 2 месяца",
        "Залог 200 у.е.",
    ],
)
def test_keyword_fallback_detects_deposit(text: str) -> None:
    assert mentions_deposit(text)
    finding = prepayment(deposit_requested=None, prepay_before_viewing=None, text=text)
    assert finding is not None and finding.code == "deposit"


@pytest.mark.parametrize(
    "text",
    [
        "БЕЗ ДЕПОЗИТА И ПРЕДОПЛАТЫ за 2 ой месяц",
        "Без залога, оплата помесячно",
        "Depozitsiz, oyma-oy to'lov",
        "Zaklad yo'q",
        "Depozit kerak emas",
        "Chilonzor 5-kvartal, 2 xona, mebel bor",
    ],
)
def test_keyword_fallback_respects_negation(text: str) -> None:
    assert not mentions_deposit(text)


@pytest.mark.parametrize(
    "text",
    [
        "Ko'rishdan oldin 100$ pul o'tkazing",
        "Bron uchun kartaga pul tashlang",
        "Предоплата до просмотра",
        "Для брони перевод на карту",
    ],
)
def test_keyword_fallback_detects_prepay_before_viewing(text: str) -> None:
    assert mentions_prepay_before_viewing(text)
    finding = prepayment(deposit_requested=None, prepay_before_viewing=None, text=text)
    assert finding is not None and finding.code == "prepay_before_viewing"


def test_keyword_fallback_no_prepay_before_viewing_in_normal_text() -> None:
    assert not mentions_prepay_before_viewing(
        "Ko'rish uchun qo'ng'iroq qiling, kartadan to'lash mumkin"
    )


# ------------------------------------------------------------ telefon


def test_phone_reuse_flags_many_listings() -> None:
    finding = phone_reuse(3)
    assert finding is not None and finding.penalty == 15
    heavy = phone_reuse(8)
    assert heavy is not None and heavy.penalty == 25


def test_phone_reuse_allows_few_listings() -> None:
    assert phone_reuse(0) is None
    assert phone_reuse(2) is None


# ------------------------------------------------------------ rasm


def test_photos_flags_missing_photo() -> None:
    finding = photos(has_photo=False)
    assert finding is not None and finding.code == "no_photo"


def test_photos_flags_photo_reused_by_another_phone() -> None:
    finding = photos(has_photo=True, reused_elsewhere=1)
    assert finding is not None and finding.code == "photo_reused"


def test_photos_ok_with_own_photo() -> None:
    assert photos(has_photo=True, reused_elsewhere=0) is None


# ------------------------------------------------------------ eskirish


def test_stale_flags_old_listing() -> None:
    warn = stale(NOW - timedelta(days=14), NOW)
    assert warn is not None and warn.penalty == 15
    old = stale(NOW - timedelta(days=45), NOW)
    assert old is not None and old.penalty == 35
    assert "45 kun" in old.reason


def test_stale_ignores_fresh_listing() -> None:
    assert stale(NOW - timedelta(days=13, hours=23), NOW) is None
    assert stale(NOW, NOW) is None


# ------------------------------------------------------------ umumiy ball


def test_trust_score_is_clamped() -> None:
    assert trust_score([]) == 100
    assert trust_score([Finding("a", 30, "x"), Finding("b", 15, "y")]) == 55
    assert trust_score([Finding("a", 80, "x"), Finding("b", 80, "y")]) == 0


def _input(**overrides: object) -> RuleInput:
    values: dict[str, object] = {
        "price_usd": 400,
        "median_usd": 420.0,
        "deposit_requested": False,
        "prepay_before_viewing": False,
        "text": "",
        "other_listings_with_phone": 0,
        "has_photo": True,
        "photo_reused_elsewhere": 0,
        "last_seen_at": NOW,
        "now": NOW,
    }
    values.update(overrides)
    return RuleInput(**values)  # type: ignore[arg-type]


def test_evaluate_clean_listing_scores_100() -> None:
    trust = evaluate(_input())
    assert trust.score == 100
    assert trust.reasons == []


def test_evaluate_combines_findings_sorted_by_severity() -> None:
    trust = evaluate(
        _input(price_usd=150, median_usd=400.0, prepay_before_viewing=True, has_photo=False)
    )
    assert [finding.code for finding in trust.findings] == [
        "below_market",
        "prepay_before_viewing",
        "no_photo",
    ]
    assert trust.score == 0  # 50 + 45 + 15 > 100
    assert len(trust.reasons) == 3
