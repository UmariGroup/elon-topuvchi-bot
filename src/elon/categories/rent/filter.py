"""Ijara qidiruv filtri: moslik va saralash (pure)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from elon.categories.rent.districts import DISTRICTS, district_name

ForWhom = Literal["oila", "talaba", "qizlar", "yigitlar", "chet_ellik"]
RentalType = Literal["kvartira", "xona_sherik"]

_FOR_WHOM_LABEL = {
    "oila": "oila",
    "talaba": "talabalar",
    "qizlar": "qizlar",
    "yigitlar": "yigitlar",
    "chet_ellik": "chet elliklar",
    "har_kim": "har kim",
}


class RentFilter(BaseModel):
    districts: list[str] = Field(default_factory=list)
    rooms: list[int] = Field(default_factory=list)
    price_max_usd: int | None = None
    price_min_usd: int | None = None
    rental_type: RentalType = "kvartira"
    for_whom: ForWhom | None = None
    furnished: bool | None = None
    duration_months: int | None = None

    @field_validator("districts", mode="before")
    @classmethod
    def _known_districts(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [item for item in value if item in DISTRICTS]
        return value

    @field_validator("rooms", mode="before")
    @classmethod
    def _valid_rooms(cls, value: Any) -> Any:
        if isinstance(value, list):
            return sorted({item for item in value if isinstance(item, int) and 1 <= item <= 10})
        return value

    @field_validator("price_max_usd", "price_min_usd", "duration_months", mode="before")
    @classmethod
    def _positive(cls, value: Any) -> Any:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return round(value) if value > 0 else None
        return None

    def describe(self) -> str:
        """Filtrning foydalanuvchiga ko'rsatiladigan ko'rinishi."""
        lines = [
            "📍 Tuman: " + (", ".join(DISTRICTS[d] for d in self.districts) or "farqi yo'q"),
            "🚪 Xonalar: " + (", ".join(str(r) for r in self.rooms) or "farqi yo'q"),
        ]
        if self.price_max_usd and self.price_min_usd:
            lines.append(f"💵 Narx: {self.price_min_usd}–{self.price_max_usd}$ / oy")
        elif self.price_max_usd:
            lines.append(f"💵 Narx: {self.price_max_usd}$ gacha / oy")
        elif self.price_min_usd:
            lines.append(f"💵 Narx: {self.price_min_usd}$ dan / oy")
        else:
            lines.append("💵 Narx: cheklanmagan")
        lines.append(
            "🏠 Turi: "
            + ("butun kvartira" if self.rental_type == "kvartira" else "xona / sheriklikka")
        )
        if self.for_whom:
            lines.append(f"👥 Kim uchun: {_FOR_WHOM_LABEL[self.for_whom]}")
        if self.furnished is not None:
            lines.append("🛋 Mebel: " + ("kerak" if self.furnished else "mebelsiz"))
        if self.duration_months:
            lines.append(f"🗓 Muddat: {self.duration_months} oy")
        return "\n".join(lines)


@dataclass(frozen=True)
class ListingView:
    """Moslik va saralash uchun e'lonning kerakli maydonlari (ORM'dan mustaqil)."""

    id: int
    location: str | None
    price_usd: int | None
    attrs: dict[str, Any]
    trust_score: int
    last_seen_at: datetime


def matches(flt: RentFilter, listing: ListingView) -> bool:
    attrs = listing.attrs
    if flt.districts and listing.location not in flt.districts:
        return False
    if flt.rooms and attrs.get("rooms") not in flt.rooms:
        return False
    if flt.price_max_usd is not None and (
        listing.price_usd is None or listing.price_usd > flt.price_max_usd
    ):
        return False
    if flt.price_min_usd is not None and (
        listing.price_usd is None or listing.price_usd < flt.price_min_usd
    ):
        return False
    # Quyidagilar "yumshoq": e'londa ko'rsatilmagan bo'lsa (None) o'tkaziladi
    rental_type = attrs.get("rental_type")
    if rental_type is not None and rental_type != flt.rental_type:
        return False
    furnished = attrs.get("furnished")
    if flt.furnished is not None and furnished is not None and furnished != flt.furnished:
        return False
    accepted = attrs.get("for_whom") or []
    return not (
        flt.for_whom is not None
        and accepted
        and flt.for_whom not in accepted
        and "har_kim" not in accepted
    )


def rank_score(flt: RentFilter, listing: ListingView, now: datetime) -> float:
    """Katta bo'lsa yaxshi: ishonch balli, yangilik va ma'lumot to'liqligi."""
    age_days = max(0.0, (now - listing.last_seen_at).total_seconds() / 86_400)
    score = float(listing.trust_score) - 2.0 * age_days
    attrs = listing.attrs
    if flt.furnished is not None and attrs.get("furnished") is None:
        score -= 5
    if flt.for_whom is not None and not attrs.get("for_whom"):
        score -= 5
    if attrs.get("rental_type") is None:
        score -= 5
    if listing.price_usd is None:
        score -= 10
    return score


def format_listing(
    *,
    summary: str,
    location: str | None,
    price_usd: int | None,
    attrs: dict[str, Any],
    is_agent: bool | None,
    trust_score: int,
    trust_reasons: list[str],
    source_url: str,
    posted_at: datetime,
    now: datetime,
) -> str:
    """Bitta e'lonning foydalanuvchiga ko'rinishi. Telefon raqam ataylab ko'rsatilmaydi."""
    place = ", ".join(part for part in (district_name(location), attrs.get("landmark")) if part)
    facts: list[str] = []
    if price_usd is not None:
        facts.append(f"{price_usd}$ / oy")
    if attrs.get("rooms"):
        facts.append(f"{attrs['rooms']} xona")
    if attrs.get("area_m2"):
        facts.append(f"{attrs['area_m2']:g} m²")
    if attrs.get("floor") and attrs.get("floors_total"):
        facts.append(f"{attrs['floor']}/{attrs['floors_total']}-qavat")
    if attrs.get("furnished") is True:
        facts.append("mebelli")
    if is_agent is True:
        facts.append("vositachi")
    elif is_agent is False:
        facts.append("egasidan")

    days = (now - posted_at).days
    when = "bugun" if days <= 0 else "kecha" if days == 1 else f"{days} kun oldin"

    lines = [f"🏠 {summary}"]
    if place:
        lines.append(f"📍 {place}")
    if facts:
        lines.append("💵 " + " · ".join(facts))
    lines.append(f"🕒 {when}")
    lines.append(f"🛡 Ishonch balli: {trust_score}/100")
    if trust_reasons:
        lines.extend(f"  • {reason}" for reason in trust_reasons)
    else:
        lines.append("  • Shubhali belgi topilmadi")
    lines.append(f"🔗 Manba: {source_url}")
    return "\n".join(lines)
