"""Parser aniqligini qo'lda belgilangan namunada o'lchash (qabul mezoni: >= 85%).

1) Namuna olish (bazadagi real postlardan tasodifiy 100 ta):
       python -m elon.tools.eval_parser export --n 100
   -> reports/data/samples.csv (bu fayl repoga qo'shilmaydi: ichida begona telefonlar bor)

2) CSV'ni Excel/Google Sheets'da ochib, HAR BIR qatorni ODAM qo'lda belgilaydi
   (ustunlar pastda, `LABEL_COLUMNS`). Bo'sh katak = "e'londa ko'rsatilmagan".

3) Baholash (Claude'ni chaqiradi, natijani reports/parser_eval.md ga yozadi):
       python -m elon.tools.eval_parser run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select

from elon.categories import get_category
from elon.categories.base import Extracted
from elon.categories.rent.districts import DISTRICTS
from elon.categories.rent.extract import normalize_price
from elon.config import Settings, get_settings
from elon.db.models import RawPost
from elon.db.session import init_db, make_engine, make_sessionmaker
from elon.llm.client import AnthropicLLM, LLMClient
from elon.llm.pricing import TokenUsage, cost_micro_usd
from elon.llm.usage import record_ai_call
from elon.timeutil import TASHKENT, utcnow

CATEGORY = "rent"
TARGET_ACCURACY = 0.85
META_COLUMNS = ["post_id", "source_url", "text"]
LABEL_COLUMNS = [
    "is_listing",  # 1 = Toshkentda uzoq muddatli kvartira/xona ijarasi taklifi, 0 = boshqa narsa
    "district",  # tuman kaliti: chilonzor, yunusobod, mirzo_ulugbek, ...
    "rental_type",  # kvartira | xona_sherik
    "rooms",
    "floor",
    "floors_total",
    "area_m2",
    "price_amount",  # e'londagi oylik narx (raqam)
    "price_currency",  # USD | UZS
    "furnished",  # 1 | 0
    "poster",  # egasi | vositachi
]
FIELDS = [
    "is_listing",
    "district",
    "rental_type",
    "rooms",
    "floor",
    "floors_total",
    "area_m2",
    "price_usd",
    "furnished",
    "poster",
]


class LabelError(ValueError):
    pass


@dataclass(frozen=True)
class Expected:
    post_id: int
    text: str
    is_listing: bool
    values: dict[str, Any]


@dataclass
class Mismatch:
    post_id: int
    field: str
    expected: Any
    actual: Any


@dataclass
class EvalResult:
    samples: int = 0
    correct: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    total: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    mismatches: list[Mismatch] = field(default_factory=list)
    cost_micro_usd: int = 0

    @property
    def accuracy(self) -> float:
        total = sum(self.total.values())
        return sum(self.correct.values()) / total if total else 0.0


# ------------------------------------------------------------ belgilarni o'qish (pure)


def _cell(row: dict[str, str], name: str) -> str:
    return (row.get(name) or "").strip()


def _number(row: dict[str, str], name: str) -> float | None:
    raw = _cell(row, name).replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise LabelError(f"post {row.get('post_id')}: '{name}' raqam emas: {raw!r}") from None


def _flag(row: dict[str, str], name: str) -> bool | None:
    raw = _cell(row, name).lower()
    if not raw:
        return None
    if raw in ("1", "ha", "true", "yes"):
        return True
    if raw in ("0", "yo'q", "yoq", "false", "no"):
        return False
    raise LabelError(f"post {row.get('post_id')}: '{name}' 1 yoki 0 bo'lishi kerak: {raw!r}")


def _choice(row: dict[str, str], name: str, allowed: set[str]) -> str | None:
    raw = _cell(row, name).lower()
    if not raw:
        return None
    if raw not in allowed:
        raise LabelError(f"post {row.get('post_id')}: '{name}' noto'g'ri qiymat: {raw!r}")
    return raw


def parse_label_row(row: dict[str, str], usd_uzs_rate: int) -> Expected:
    is_listing = _flag(row, "is_listing")
    if is_listing is None:
        raise LabelError(f"post {row.get('post_id')}: 'is_listing' to'ldirilmagan")
    whole = _number(row, "rooms")
    floor, floors_total = _number(row, "floor"), _number(row, "floors_total")
    currency = _choice(row, "price_currency", {"usd", "uzs"})
    price_usd, _, _ = normalize_price(
        _number(row, "price_amount"), currency.upper() if currency else None, usd_uzs_rate
    )
    return Expected(
        post_id=int(row["post_id"]),
        text=row["text"],
        is_listing=is_listing,
        values={
            "district": _choice(row, "district", set(DISTRICTS)),
            "rental_type": _choice(row, "rental_type", {"kvartira", "xona_sherik"}),
            "rooms": round(whole) if whole is not None else None,
            "floor": round(floor) if floor is not None else None,
            "floors_total": round(floors_total) if floors_total is not None else None,
            "area_m2": _number(row, "area_m2"),
            "price_usd": price_usd,
            "furnished": _flag(row, "furnished"),
            "poster": _choice(row, "poster", {"egasi", "vositachi"}),
        },
    )


def predicted_values(extracted: Extracted) -> dict[str, Any]:
    attrs = extracted.attrs
    poster = {True: "vositachi", False: "egasi"}.get(extracted.is_agent)  # type: ignore[arg-type]
    return {
        "district": extracted.location,
        "rental_type": attrs.get("rental_type"),
        "rooms": attrs.get("rooms"),
        "floor": attrs.get("floor"),
        "floors_total": attrs.get("floors_total"),
        "area_m2": attrs.get("area_m2"),
        "price_usd": extracted.price_usd,
        "furnished": attrs.get("furnished"),
        "poster": poster,
    }


def _equal(name: str, expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if name == "area_m2":
        return abs(float(expected) - float(actual)) <= 1.0
    if name == "price_usd":
        return abs(int(expected) - int(actual)) <= max(2, round(int(expected) * 0.02))
    return bool(expected == actual)


def compare(expected: Expected, extracted: Extracted | None, result: EvalResult) -> None:
    """Bitta namunani solishtirib, natijani `result` ga qo'shadi."""
    result.samples += 1
    predicted_listing = extracted is not None
    result.total["is_listing"] += 1
    if predicted_listing == expected.is_listing:
        result.correct["is_listing"] += 1
    else:
        result.mismatches.append(
            Mismatch(expected.post_id, "is_listing", expected.is_listing, predicted_listing)
        )
    if not expected.is_listing:
        return  # e'lon bo'lmagan post uchun maydonlar baholanmaydi
    actual = predicted_values(extracted) if extracted is not None else {}
    for name, want in expected.values.items():
        result.total[name] += 1
        got = actual.get(name) if extracted is not None else "(e'lon deb topilmadi)"
        if extracted is not None and _equal(name, want, got):
            result.correct[name] += 1
        else:
            result.mismatches.append(Mismatch(expected.post_id, name, want, got))


def render_report(result: EvalResult, *, model: str, when: datetime) -> str:
    passed = result.accuracy >= TARGET_ACCURACY
    lines = [
        "# Parser aniqligi bahosi",
        "",
        f"- Sana: {when.astimezone(TASHKENT):%Y-%m-%d %H:%M} (Toshkent)",
        f"- Model: `{model}`",
        f"- Qo'lda belgilangan namunalar: {result.samples}",
        f"- **Umumiy aniqlik: {result.accuracy:.1%}** (talab: ≥ {TARGET_ACCURACY:.0%}) — "
        + ("✅ bajarildi" if passed else "❌ bajarilmadi"),
        f"- Baholash xarajati: ${result.cost_micro_usd / 1_000_000:.4f}",
        "",
        "Aniqlik = to'g'ri ajratilgan maydonlar / barcha tekshirilgan maydonlar. "
        "`is_listing` barcha namunalarda, qolgan maydonlar faqat e'lon deb belgilangan "
        "namunalarda tekshiriladi. Bo'sh belgi = model ham `null` qaytarishi kerak. "
        "Maydon xatosi: model e'lonni topmagan bo'lsa, uning barcha maydonlari xato sanaladi.",
        "",
        "| Maydon | To'g'ri | Jami | Aniqlik |",
        "|---|---:|---:|---:|",
    ]
    for name in FIELDS:
        total = result.total[name]
        share = f"{result.correct[name] / total:.1%}" if total else "—"
        lines.append(f"| `{name}` | {result.correct[name]} | {total} | {share} |")
    lines += ["", f"## Xatolar ({len(result.mismatches)})", ""]
    if result.mismatches:
        lines += ["| post_id | maydon | kutilgan | model |", "|---:|---|---|---|"]
        lines += [
            f"| {m.post_id} | `{m.field}` | {m.expected} | {m.actual} |" for m in result.mismatches
        ]
    else:
        lines.append("Xato yo'q.")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ baza va AI bilan ishlash


async def export_samples(settings: Settings, count: int) -> list[tuple[int, str, str]]:
    engine = make_engine(settings.database_url.get_secret_value())
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        rows = await session.execute(
            select(RawPost.id, RawPost.source_url, RawPost.text)
            .where(
                RawPost.category == CATEGORY,
                RawPost.status.in_(("parsed", "skipped")),
                # faqat AI'ga yuborilgan postlar (prefiltrda tushib qolganlar emas)
                or_(RawPost.skip_reason.is_(None), RawPost.skip_reason == "not_listing"),
            )
            .order_by(func.random())
            .limit(count)
        )
        posts = [(post_id, url, text) for post_id, url, text in rows]
    await engine.dispose()
    return posts


async def evaluate_rows(
    rows: list[dict[str, str]], llm: LLMClient, settings: Settings
) -> EvalResult:
    category = get_category(CATEGORY)
    assert category is not None
    result = EvalResult()
    for row in rows:
        expected = parse_label_row(row, settings.usd_uzs_rate)
        response = await llm.call_tool(
            model=settings.parser_model,
            system=category.parser_system_prompt,
            messages=[{"role": "user", "content": f"<post>\n{expected.text[:4000]}\n</post>"}],
            tool=category.parser_tool,
            max_tokens=700,
        )
        result.cost_micro_usd += cost_micro_usd(settings.parser_model, response.usage)
        extracted = category.build(
            response.data, text=expected.text, usd_uzs_rate=settings.usd_uzs_rate
        )
        compare(expected, extracted, result)
    return result


async def record_eval_cost(settings: Settings, micro_usd: int, now: datetime) -> None:
    """Baholash xarajati ham kunlik AI hisobiga kiradi."""
    engine = make_engine(settings.database_url.get_secret_value())
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        call = await record_ai_call(
            session, purpose="eval", model=settings.parser_model, usage=TokenUsage(), now=now
        )
        call.cost_micro_usd = micro_usd
        await session.commit()
    await engine.dispose()


async def run_eval(settings: Settings, rows: list[dict[str, str]]) -> EvalResult:
    llm = AnthropicLLM(settings.anthropic_api_key.get_secret_value())
    result = await evaluate_rows(rows, llm, settings)
    await record_eval_cost(settings, result.cost_micro_usd, utcnow())
    return result


def read_rows(source: Path) -> list[dict[str, str]]:
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_samples(posts: list[tuple[int, str, str]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=META_COLUMNS + LABEL_COLUMNS)
        writer.writeheader()
        for post_id, url, text in posts:
            writer.writerow({"post_id": post_id, "source_url": url, "text": text})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="bazadan tasodifiy namunalar olish")
    export.add_argument("--n", type=int, default=100)
    export.add_argument("--out", type=Path, default=Path("reports/data/samples.csv"))
    run = commands.add_parser("run", help="belgilangan namunada parserni baholash")
    run.add_argument("--in", dest="source", type=Path, default=Path("reports/data/samples.csv"))
    run.add_argument("--report", type=Path, default=Path("reports/parser_eval.md"))
    args = parser.parse_args()
    settings = get_settings()

    if args.command == "export":
        posts = asyncio.run(export_samples(settings, args.n))
        write_samples(posts, args.out)
        print(f"{len(posts)} ta namuna yozildi: {args.out}")
        return
    try:
        result = asyncio.run(run_eval(settings, read_rows(args.source)))
    except LabelError as exc:
        sys.exit(f"Belgilashda xato: {exc}")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        render_report(result, model=settings.parser_model, when=utcnow()), encoding="utf-8"
    )
    print(f"Aniqlik: {result.accuracy:.1%} ({result.samples} namuna). Hisobot: {args.report}")
    if result.accuracy < TARGET_ACCURACY:
        sys.exit(1)


if __name__ == "__main__":
    main()
