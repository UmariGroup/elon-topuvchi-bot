from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from elon.db.models import Channel, Listing, RawPost
from elon.pipeline.dedup import text_hash

_counter = 0


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def rent_text(n: int | None = None) -> str:
    """Prefiltrdan o'tadigan, har biri boshqacha e'lon matni."""
    n = n if n is not None else _next()
    return (
        f"Ijaraga kvartira beriladi, variant raqami {n}. Chilonzor {n}-kvartal, metro yaqinida, "
        f"{n} yil oldin ta'mirlangan, oilaga. Narxi kelishiladi, mebel bor, uy raqami {n * 7}."
    )


def rent_data(**overrides: Any) -> dict[str, Any]:
    """Model (record_listing tool) qaytaradigan javob namunasi."""
    data: dict[str, Any] = {
        "is_listing": True,
        "district": "chilonzor",
        "landmark": "Chilonzor metro",
        "rental_type": "kvartira",
        "rooms": 2,
        "floor": 3,
        "floors_total": 9,
        "area_m2": 54,
        "price_amount": 400,
        "price_currency": "USD",
        "furnished": True,
        "for_whom": ["oila"],
        "poster": "egasi",
        "phone": None,
        "deposit_requested": None,
        "prepay_before_viewing": None,
        "summary_uz": "Chilonzorda 2 xonali, mebelli kvartira.",
    }
    data.update(overrides)
    return data


async def make_channel(
    session: AsyncSession, username: str = "test_ijara", **kwargs: Any
) -> Channel:
    channel = Channel(username=username, category=kwargs.pop("category", "rent"), **kwargs)
    session.add(channel)
    await session.flush()
    return channel


async def make_raw_post(
    session: AsyncSession,
    channel: Channel,
    now: datetime,
    *,
    text: str | None = None,
    **kwargs: Any,
) -> RawPost:
    message_id = kwargs.pop("message_id", _next())
    body = text if text is not None else rent_text()
    post = RawPost(
        channel_id=channel.id,
        message_id=message_id,
        category=channel.category,
        posted_at=kwargs.pop("posted_at", now),
        collected_at=now,
        text=body,
        text_hash=text_hash(body),
        has_photo=kwargs.pop("has_photo", True),
        photo_fp=kwargs.pop("photo_fp", None),
        source_url=f"https://t.me/{channel.username}/{message_id}",
        status=kwargs.pop("status", "new"),
        **kwargs,
    )
    session.add(post)
    await session.flush()
    return post


async def make_listing(
    session: AsyncSession, channel: Channel, now: datetime, **kwargs: Any
) -> Listing:
    """Tayyor (tahlil qilingan) e'lon — qidiruv va bildirishnoma testlari uchun."""
    posted_at = kwargs.pop("posted_at", now)
    post = await make_raw_post(
        session, channel, now, posted_at=posted_at, status="parsed", text=kwargs.pop("text", None)
    )
    attrs: dict[str, Any] = {
        "landmark": "Chilonzor metro",
        "rental_type": "kvartira",
        "rooms": 2,
        "floor": 3,
        "floors_total": 9,
        "area_m2": 54,
        "furnished": True,
        "for_whom": ["oila"],
    }
    attrs.update(kwargs.pop("attrs", {}))
    location = kwargs.pop("location", "chilonzor")
    listing = Listing(
        raw_post_id=post.id,
        category="rent",
        source_url=post.source_url,
        posted_at=posted_at,
        last_seen_at=kwargs.pop("last_seen_at", posted_at),
        created_at=now,
        location=location,
        segment=kwargs.pop("segment", f"{location}|{attrs['rooms']}"),
        price_usd=kwargs.pop("price_usd", 400),
        summary=kwargs.pop("summary", "Chilonzorda 2 xonali, mebelli kvartira."),
        has_photo=kwargs.pop("has_photo", True),
        attrs=attrs,
        trust_score=kwargs.pop("trust_score", 100),
        trust_reasons=kwargs.pop("trust_reasons", []),
        **kwargs,
    )
    session.add(listing)
    await session.flush()
    return listing
