"""Pure funksiyalar: narx hisobi, telefon, dublikat, ijara ajratish, filtr, log."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pytest

from elon.categories.rent.extract import RENT, normalize_price, segment_key
from elon.categories.rent.filter import (
    ListingView,
    RentFilter,
    format_listing,
    matches,
    rank_score,
)
from elon.categories.rent.prompts import CHAT_SYSTEM, PARSER_SYSTEM
from elon.config import Settings
from elon.db.session import normalize_url
from elon.llm.pricing import TokenUsage, UnknownModelError, cost_micro_usd, price_for
from elon.logsetup import RedactPhones
from elon.pipeline.dedup import DedupKey, is_duplicate, similarity, text_hash
from elon.pipeline.phones import extract_phones, hash_phone, normalize_phone
from elon.timeutil import tashkent_day_start
from tests.conftest import NOW
from tests.factories import rent_data

# ------------------------------------------------------------ sozlamalar


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "TELEGRAM_BOT_TOKEN": "1:maxfiy-bot",
        "TG_API_ID": "12345",
        "TG_API_HASH": "maxfiy-hash",
        "ANTHROPIC_API_KEY": "maxfiy-key",
        "DATABASE_URL": "postgresql://elon:parol@db:5432/elon",
        "ADMIN_IDS": "111, 222",
        "TRIAL_DAYS": "10",
        "DAILY_AI_BUDGET_USD": "2.5",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.admin_ids == [111, 222]
    assert settings.trial_days == 10
    assert settings.daily_budget_micro_usd == 2_500_000
    assert settings.phone_hash_key == b"maxfiy-hash"
    # Kalitlar va baza paroli tasodifan logga chiqmaydi
    assert all(secret not in repr(settings) for secret in ("maxfiy", "parol"))
    url = normalize_url(settings.database_url.get_secret_value())
    assert url == "postgresql+asyncpg://elon:parol@db:5432/elon"

    monkeypatch.setenv("ADMIN_IDS", "")
    assert Settings(_env_file=None).admin_ids == []


# ------------------------------------------------------------ AI narxi


def test_cost_haiku() -> None:
    usage = TokenUsage(input_tokens=1000, output_tokens=200, cache_read_tokens=2000)
    # 1000*0.10 + 200*0.50 + 2000*0.01 = 220 mikro-dollar
    assert cost_micro_usd("claude-haiku-5-5", usage) == 220


def test_cost_sonnet_with_cache_write() -> None:
    usage = TokenUsage(input_tokens=500, output_tokens=300, cache_write_tokens=1000)
    # 500*2 + 300*10 + 1000*2.5 = 6500
    assert cost_micro_usd("claude-sonnet-5-5", usage) == 6500


def test_cost_haiku_long_prompt_tier() -> None:
    usage = TokenUsage(input_tokens=100_001, output_tokens=0)
    assert cost_micro_usd("claude-haiku-5-5", usage) == 50_001  # 5 barobar (yuqoriga yaxlitlangan)


def test_cost_rounds_up() -> None:
    assert cost_micro_usd("claude-haiku-5-5", TokenUsage(cache_read_tokens=1)) == 1


def test_unknown_model_is_an_error() -> None:
    with pytest.raises(UnknownModelError):
        price_for("claude-nomalum")


def test_tashkent_day_start() -> None:
    # NOW = 13-noyabr 12:00 Toshkent -> kun boshi 12-noyabr 19:00 UTC
    start = tashkent_day_start(NOW)
    assert start.isoformat() == "2026-11-12T19:00:00+00:00"


# ------------------------------------------------------------ telefon


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+998 90 123 45 67", "998901234567"),
        ("90-123-45-67", "998901234567"),
        ("(93) 555 11 22", "998935551122"),
        ("998977000000", "998977000000"),
    ],
)
def test_normalize_phone(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "12345", "+7 912 345 67 89", "00 123 45 67"])
def test_normalize_phone_rejects_invalid(raw: str | None) -> None:
    assert normalize_phone(raw) is None


def test_extract_phones_from_text() -> None:
    text = "Narxi 400$, 54 m². Tel: +998 90 123-45-67 yoki 93 555 11 22. 2026-yil"
    assert extract_phones(text) == ["998901234567", "998935551122"]


def test_hash_phone_is_keyed_and_hides_number() -> None:
    first = hash_phone("998901234567", b"kalit-1")
    assert first == hash_phone("998901234567", b"kalit-1")
    assert first != hash_phone("998901234567", b"kalit-2")
    assert "901234567" not in first


# ------------------------------------------------------------ dublikat

BASE = (
    "Ijaraga 2 xonali kvartira Chilonzor 7-kvartal Novza metro yonida 3-qavat mebel "
    "va texnika bor oilaga beriladi narxi 400$ egasidan"
)


def test_similarity_bounds() -> None:
    assert similarity(BASE, BASE) == 1.0
    assert (
        similarity(BASE, "Sergeli 5 da 3 xonali uy sotiladi 60000 dollar hujjatlari tayyor") == 0.0
    )
    assert similarity("", BASE) == 0.0


def test_text_hash_ignores_case_spacing_and_links() -> None:
    assert text_hash(BASE) == text_hash("  " + BASE.upper().replace(" ", "   ") + " @kanal t.me/x ")
    assert text_hash(BASE) != text_hash(BASE + " yangi")


def test_duplicate_same_text() -> None:
    new = DedupKey(BASE + " 👍", None, None, None)
    assert is_duplicate(new, DedupKey(BASE, None, None, None))


def test_duplicate_same_phone_price_and_similar_text() -> None:
    reworded = BASE.replace("Novza metro yonida", "Novza metrosiga 5 daqiqa") + " shoshiling"
    new = DedupKey(reworded, "ph", 400, None)
    assert is_duplicate(new, DedupKey(BASE, "ph", 400, None))


def test_duplicate_same_phone_price_segment_even_if_text_rewritten() -> None:
    new = DedupKey(
        "Kvartira arenda, hamma sharoit bor, qo'ng'iroq qiling", "ph", 400, "chilonzor|2"
    )
    assert is_duplicate(new, DedupKey(BASE, "ph", 400, "chilonzor|2"))


def test_not_duplicate_when_price_differs() -> None:
    reworded = BASE.replace("400$", "550$").replace("7-kvartal", "12-kvartal")
    new = DedupKey(reworded, "ph", 550, "chilonzor|2")
    assert not is_duplicate(new, DedupKey(BASE, "ph", 400, "chilonzor|2"))


def test_not_duplicate_when_phone_differs_and_text_differs() -> None:
    other = "Yunusobod 4 da 2 xonali kvartira ijaraga, yangi ta'mir, 400$, talabalarga ham bo'ladi"
    assert not is_duplicate(
        DedupKey(other, "ph-2", 400, "yunusobod|2"), DedupKey(BASE, "ph-1", 400, "chilonzor|2")
    )


# ------------------------------------------------------------ ijara: ajratish


def test_normalize_price_usd_and_uzs() -> None:
    assert normalize_price(400, "USD", 12_700) == (400, 400, "USD")
    assert normalize_price(5_080_000, "UZS", 12_700) == (400, 5_080_000, "UZS")


@pytest.mark.parametrize(
    ("amount", "currency"),
    [
        (None, "USD"),
        (400, None),
        (400, "EUR"),
        (5, "USD"),
        (62_000, "USD"),
        (400, "UZS"),
        (-1, "USD"),
    ],
)
def test_normalize_price_rejects_implausible(amount: float | None, currency: str | None) -> None:
    assert normalize_price(amount, currency, 12_700) == (None, None, None)


def test_segment_key_only_for_whole_apartments() -> None:
    assert segment_key("chilonzor", 2, "kvartira") == "chilonzor|2"
    assert segment_key("chilonzor", 2, "xona_sherik") is None
    assert segment_key(None, 2, "kvartira") is None


def test_prefilter() -> None:
    assert RENT.prefilter("ijara") == "too_short"
    assert RENT.prefilter(
        "Bugun havo ochiq, harorat +15 daraja, yomg'ir kutilmaydi, hammaga omad"
    ) == ("no_rent_keywords")
    assert RENT.prefilter("Сдаётся 2-комнатная квартира на Чиланзаре, 400 у.е., мебель") is None


def test_build_normalizes_fields() -> None:
    text = "Ijaraga kvartira, Chilonzor. Tel: 90 123 45 67"
    extracted = RENT.build(
        rent_data(price_amount=5_080_000, price_currency="UZS", poster="vositachi"),
        text=text,
        usd_uzs_rate=12_700,
    )
    assert extracted is not None
    assert extracted.location == "chilonzor"
    assert extracted.segment == "chilonzor|2"
    assert extracted.price_usd == 400
    assert extracted.price_original == 5_080_000
    assert extracted.is_agent is True
    assert extracted.phone == "998901234567"  # regex orqali matndan
    assert extracted.attrs["rooms"] == 2
    assert extracted.attrs["for_whom"] == ["oila"]


def test_build_returns_none_for_non_listing() -> None:
    assert (
        RENT.build({"is_listing": False, "summary_uz": "Sotuv"}, text="x", usd_uzs_rate=1) is None
    )
    assert RENT.build({"summary_uz": "?"}, text="x", usd_uzs_rate=1) is None


def test_build_drops_untrusted_values() -> None:
    data = rent_data(
        district="tokio",
        rooms=45,
        floor=12,
        floors_total=5,
        area_m2=3,
        for_whom=["oila", "robot"],
        poster="kimdir",
        furnished="ha",
        rental_type="villa",
    )
    extracted = RENT.build(data, text="matn", usd_uzs_rate=12_700)
    assert extracted is not None
    assert extracted.location is None
    assert extracted.segment is None
    assert extracted.is_agent is None
    assert extracted.attrs == {
        "landmark": "Chilonzor metro",
        "rental_type": None,
        "rooms": None,
        "floor": None,
        "floors_total": None,
        "area_m2": None,
        "furnished": None,
        "for_whom": ["oila"],
    }


def test_prompts_are_static_and_long_enough_to_cache() -> None:
    # Kesh ishlashi uchun prompt o'zgarmas va yetarlicha uzun bo'lishi kerak (taxminan 4 belgi = 1 token)
    assert len(PARSER_SYSTEM) > 5000
    assert len(CHAT_SYSTEM) > 3000
    assert "{" not in CHAT_SYSTEM.replace("{json}", "")


# ------------------------------------------------------------ ijara: filtr


def _view(**overrides: Any) -> ListingView:
    values: dict[str, Any] = {
        "id": 1,
        "location": "chilonzor",
        "price_usd": 400,
        "attrs": {"rooms": 2, "rental_type": "kvartira", "furnished": True, "for_whom": ["oila"]},
        "trust_score": 100,
        "last_seen_at": NOW,
    }
    values.update(overrides)
    return ListingView(**values)


def test_filter_validation_cleans_input() -> None:
    flt = RentFilter.model_validate(
        {"districts": ["chilonzor", "mars"], "rooms": [3, 2, 2, 99], "price_max_usd": -5}
    )
    assert flt.districts == ["chilonzor"]
    assert flt.rooms == [2, 3]
    assert flt.price_max_usd is None


def test_matches_hard_conditions() -> None:
    flt = RentFilter(districts=["chilonzor"], rooms=[2], price_max_usd=450)
    assert matches(flt, _view())
    assert not matches(flt, _view(location="yunusobod"))
    assert not matches(flt, _view(location=None))
    assert not matches(flt, _view(attrs={"rooms": 3}))
    assert not matches(flt, _view(price_usd=500))
    assert not matches(flt, _view(price_usd=None))


def test_matches_soft_conditions_allow_unknown() -> None:
    flt = RentFilter(for_whom="talaba", furnished=True)
    assert not matches(flt, _view())  # faqat oilaga
    assert matches(flt, _view(attrs={"rooms": 2, "for_whom": []}))
    assert matches(flt, _view(attrs={"rooms": 2, "for_whom": ["har_kim"]}))
    assert not matches(flt, _view(attrs={"rooms": 2, "furnished": False}))
    assert not matches(RentFilter(), _view(attrs={"rooms": 1, "rental_type": "xona_sherik"}))
    assert matches(
        RentFilter(rental_type="xona_sherik"), _view(attrs={"rental_type": "xona_sherik"})
    )


def test_empty_filter_matches_everything_whole() -> None:
    assert matches(RentFilter(), _view(location=None, price_usd=None, attrs={}))


def test_rank_prefers_trusted_and_fresh() -> None:
    flt = RentFilter()
    trusted = _view(id=1, trust_score=90)
    risky = _view(id=2, trust_score=40)
    old = _view(id=3, trust_score=90, last_seen_at=NOW - timedelta(days=10))
    ranked = sorted([risky, old, trusted], key=lambda v: rank_score(flt, v, NOW), reverse=True)
    assert [view.id for view in ranked] == [1, 3, 2]


def test_describe_filter() -> None:
    text = RentFilter(
        districts=["chilonzor", "mirzo_ulugbek"], rooms=[2], price_max_usd=400, for_whom="oila"
    ).describe()
    assert "Chilonzor, Mirzo Ulug'bek" in text
    assert "400$ gacha" in text
    assert "oila" in text
    assert "farqi yo'q" in RentFilter().describe()


def test_format_listing_shows_score_reasons_and_link_only() -> None:
    text = format_listing(
        summary="Chilonzorda 2 xonali kvartira.",
        location="chilonzor",
        price_usd=400,
        attrs={"rooms": 2, "area_m2": 54.0, "floor": 3, "floors_total": 9, "landmark": "Novza"},
        is_agent=False,
        trust_score=65,
        trust_reasons=["E'londa rasm yo'q"],
        source_url="https://t.me/kanal/15",
        posted_at=NOW - timedelta(days=1),
        now=NOW,
    )
    assert "Chilonzor, Novza" in text
    assert "400$ / oy · 2 xona · 54 m² · 3/9-qavat · egasidan" in text
    assert "Ishonch balli: 65/100" in text
    assert "• E'londa rasm yo'q" in text
    assert "https://t.me/kanal/15" in text
    assert "kecha" in text


def test_format_listing_without_findings() -> None:
    text = format_listing(
        summary="Kvartira.",
        location=None,
        price_usd=None,
        attrs={},
        is_agent=None,
        trust_score=100,
        trust_reasons=[],
        source_url="https://t.me/kanal/1",
        posted_at=NOW,
        now=NOW,
    )
    assert "Shubhali belgi topilmadi" in text
    assert "bugun" in text


# ------------------------------------------------------------ log


def _redact(message: str) -> str:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, message, None, None)
    RedactPhones().filter(record)
    return record.getMessage()


def test_log_filter_hides_phone_numbers() -> None:
    assert _redact("yangi foydalanuvchi +998 90 123 45 67 keldi") == (
        "yangi foydalanuvchi <telefon> keldi"
    )
    assert "<telefon>" in _redact("tel 998901234567")
    assert "<telefon>" in _redact("aloqa: 90 123-45-67")


def test_log_filter_keeps_ids() -> None:
    assert _redact("user 123456789 post 5512") == "user 123456789 post 5512"
    assert _redact("tg_id=7012345678") == "tg_id=7012345678"
