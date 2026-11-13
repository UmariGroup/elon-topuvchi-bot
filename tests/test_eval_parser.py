"""Parser baholash vositasi: belgilarni o'qish, solishtirish va hisobot."""

from __future__ import annotations

from typing import Any

import pytest

from elon.categories.rent.extract import RENT
from elon.tools.eval_parser import (
    LABEL_COLUMNS,
    EvalResult,
    LabelError,
    compare,
    evaluate_rows,
    parse_label_row,
    render_report,
)
from tests.conftest import NOW, FakeLLM, make_settings
from tests.factories import rent_data

RATE = 12_700


def _row(**labels: str) -> dict[str, str]:
    row = {"post_id": "7", "source_url": "https://t.me/k/7", "text": "Ijaraga kvartira, Chilonzor"}
    row.update(dict.fromkeys(LABEL_COLUMNS, ""))
    row.update(labels)
    return row


FULL = {
    "is_listing": "1",
    "district": "chilonzor",
    "rental_type": "kvartira",
    "rooms": "2",
    "floor": "3",
    "floors_total": "9",
    "area_m2": "54",
    "price_amount": "400",
    "price_currency": "USD",
    "furnished": "1",
    "poster": "egasi",
}


def test_parse_label_row() -> None:
    expected = parse_label_row(
        _row(**{**FULL, "price_amount": "5 080 000", "price_currency": "uzs"}), RATE
    )
    assert expected.post_id == 7 and expected.is_listing is True
    assert expected.values["price_usd"] == 400
    assert expected.values["rooms"] == 2
    assert expected.values["furnished"] is True


def test_parse_label_row_empty_cells_mean_null() -> None:
    expected = parse_label_row(_row(is_listing="1"), RATE)
    assert set(expected.values.values()) == {None}


@pytest.mark.parametrize(
    "labels",
    [
        {},
        {"is_listing": "balki"},
        {"is_listing": "1", "district": "tokio"},
        {"is_listing": "1", "rooms": "ikki"},
    ],
)
def test_parse_label_row_rejects_bad_labels(labels: dict[str, str]) -> None:
    with pytest.raises(LabelError):
        parse_label_row(_row(**labels), RATE)


def _extract(**overrides: Any) -> Any:
    return RENT.build(rent_data(**overrides), text="Ijaraga kvartira", usd_uzs_rate=RATE)


def test_compare_all_correct_with_tolerances() -> None:
    result = EvalResult()
    compare(parse_label_row(_row(**FULL), RATE), _extract(area_m2=54.6, price_amount=404), result)
    assert result.accuracy == 1.0
    assert sum(result.total.values()) == 10
    assert result.mismatches == []


def test_compare_counts_field_errors() -> None:
    result = EvalResult()
    compare(
        parse_label_row(_row(**FULL), RATE),
        _extract(rooms=3, district="sergeli", floor=None),
        result,
    )
    assert {m.field for m in result.mismatches} == {"rooms", "district", "floor"}
    assert result.accuracy == 0.7


def test_compare_missed_listing_fails_every_field() -> None:
    result = EvalResult()
    compare(parse_label_row(_row(**FULL), RATE), None, result)
    assert result.accuracy == 0.0
    assert len(result.mismatches) == 10


def test_compare_non_listing_checks_only_classification() -> None:
    result = EvalResult()
    compare(parse_label_row(_row(is_listing="0"), RATE), None, result)
    compare(parse_label_row(_row(is_listing="0"), RATE), _extract(), result)
    assert (result.correct["is_listing"], result.total["is_listing"]) == (1, 2)
    assert sum(result.total.values()) == 2


async def test_evaluate_rows_and_report() -> None:
    llm = FakeLLM()
    llm.queue = [rent_data(), rent_data(rooms=1), {"is_listing": False, "summary_uz": "Sotuv"}]
    rows = [_row(**FULL), _row(**FULL), _row(is_listing="0")]

    result = await evaluate_rows(rows, llm, make_settings())

    assert result.samples == 3
    assert result.accuracy == pytest.approx(20 / 21)
    assert result.cost_micro_usd == 360  # 3 chaqiruv * 120
    assert llm.calls[0]["model"] == "claude-haiku-5-5"

    report = render_report(result, model="claude-haiku-5-5", when=NOW)
    assert "**Umumiy aniqlik: 95.2%**" in report
    assert "✅ bajarildi" in report
    assert "| `rooms` | 1 | 2 | 50.0% |" in report
    assert "| 7 | `rooms` | 2 | 1 |" in report
    assert "Ijaraga kvartira" not in report  # hisobotda e'lon matni (va telefonlar) yo'q
