"""Parser konveyeri: bir marta tahlil, dublikat, ishonch balli va kunlik AI limiti."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from elon.db.models import AdminEvent, AiCall, Listing, RawPost
from elon.db.session import SessionMaker
from elon.llm.pricing import TokenUsage
from elon.pipeline.parse import process_pending
from elon.pipeline.phones import hash_phone
from tests.conftest import NOW, FakeLLM, make_settings
from tests.factories import make_channel, make_raw_post, rent_data, rent_text


async def _count(sessionmaker: SessionMaker, model: Any, *where: Any) -> int:
    async with sessionmaker() as session:
        result = await session.execute(select(func.count()).select_from(model).where(*where))
        return int(result.scalar_one())


async def _seed_posts(sessionmaker: SessionMaker, count: int, **kwargs: Any) -> list[int]:
    async with sessionmaker() as session:
        channel = await make_channel(session)
        ids = [(await make_raw_post(session, channel, NOW, **kwargs)).id for _ in range(count)]
        await session.commit()
    return ids


async def test_post_is_parsed_and_stored(sessionmaker: SessionMaker) -> None:
    settings = make_settings()
    text = rent_text() + " Tel: +998 90 123 45 67"
    await _seed_posts(sessionmaker, 1, text=text)
    llm = FakeLLM(lambda call: rent_data())

    stats = await process_pending(sessionmaker, llm, settings, now=NOW)

    assert stats.parsed == 1
    async with sessionmaker() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        post = (await session.execute(select(RawPost))).scalar_one()
        call = (await session.execute(select(AiCall))).scalar_one()
    assert post.status == "parsed"
    assert listing.location == "chilonzor"
    assert listing.segment == "chilonzor|2"
    assert listing.price_usd == 400
    assert listing.source_url == post.source_url
    assert listing.trust_score == 100
    # Telefonning o'zi emas, faqat xeshi saqlanadi
    assert listing.phone_hash == hash_phone("998901234567", settings.phone_hash_key)
    assert "901234567" not in str(listing.attrs) + listing.summary
    # AI chaqiruvi tokenlari va narxi yozilgan
    assert call.purpose == "parse" and call.model == "claude-haiku-5-5"
    assert call.input_tokens == 300 and call.cache_read_tokens == 1500
    assert call.cost_micro_usd == 120  # 300*0.10 + 150*0.50 + 1500*0.01
    # Post matni model uchun <post> ichida, prompt esa o'zgarmas (kesh uchun)
    assert llm.calls[0]["messages"][0]["content"].startswith("<post>\n")


async def test_each_post_is_sent_to_ai_only_once(sessionmaker: SessionMaker) -> None:
    await _seed_posts(sessionmaker, 3)
    llm = FakeLLM(lambda call: rent_data(price_amount=300 + 10 * len(llm.calls)))

    await process_pending(sessionmaker, llm, make_settings(), now=NOW)
    await process_pending(sessionmaker, llm, make_settings(), now=NOW)

    assert len(llm.calls) == 3


async def test_identical_text_reuses_result_without_ai(sessionmaker: SessionMaker) -> None:
    text = rent_text()
    async with sessionmaker() as session:
        first = await make_channel(session, "kanal_a")
        second = await make_channel(session, "kanal_b")
        await make_raw_post(session, first, NOW, text=text, posted_at=NOW - timedelta(days=2))
        await make_raw_post(session, second, NOW, text=text.upper() + "  @kanal_b", posted_at=NOW)
        await session.commit()
    llm = FakeLLM(lambda call: rent_data())

    stats = await process_pending(sessionmaker, llm, make_settings(), now=NOW)

    assert len(llm.calls) == 1
    assert (stats.parsed, stats.duplicates) == (1, 1)
    async with sessionmaker() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
    assert listing.last_seen_at == NOW  # qayta joylangani uchun "yangilandi"


async def test_near_duplicate_is_linked_to_original(sessionmaker: SessionMaker) -> None:
    base = (
        "Ijaraga 2 xonali kvartira Chilonzor 7-kvartal Novza metro yonida 3-qavat mebel va "
        "texnika bor oilaga beriladi narxi 400$ egasidan tel 90 123 45 67"
    )
    async with sessionmaker() as session:
        channel = await make_channel(session)
        await make_raw_post(session, channel, NOW, text=base, posted_at=NOW - timedelta(days=1))
        await make_raw_post(session, channel, NOW, text=base + " Shoshiling, bugun ko'rish mumkin!")
        await session.commit()
    llm = FakeLLM(lambda call: rent_data())

    stats = await process_pending(sessionmaker, llm, make_settings(), now=NOW)

    assert (stats.parsed, stats.duplicates) == (1, 1)
    async with sessionmaker() as session:
        listings = list((await session.execute(select(Listing).order_by(Listing.id))).scalars())
    original, duplicate = listings
    assert original.duplicate_of_id is None
    assert duplicate.duplicate_of_id == original.id
    assert duplicate.notify_checked_at is not None  # dublikat bo'yicha bildirishnoma yo'q
    assert original.last_seen_at == NOW


async def test_non_listing_and_prefiltered_posts_are_skipped(sessionmaker: SessionMaker) -> None:
    async with sessionmaker() as session:
        channel = await make_channel(session)
        await make_raw_post(session, channel, NOW, text="Reklama")
        await make_raw_post(session, channel, NOW, text=rent_text())
        await session.commit()
    llm = FakeLLM(lambda call: {"is_listing": False, "summary_uz": "Sotuv e'loni"})

    stats = await process_pending(sessionmaker, llm, make_settings(), now=NOW)

    assert stats.skipped == 2
    assert len(llm.calls) == 1  # qisqa matn AI'ga yuborilmadi
    assert await _count(sessionmaker, Listing) == 0
    async with sessionmaker() as session:
        reasons = set((await session.execute(select(RawPost.skip_reason))).scalars())
    assert reasons == {"too_short", "not_listing"}


async def test_ai_error_is_retried_then_marked_failed(sessionmaker: SessionMaker) -> None:
    await _seed_posts(sessionmaker, 1)
    llm = FakeLLM(lambda call: RuntimeError("tarmoq xatosi"))

    for _ in range(4):
        await process_pending(sessionmaker, llm, make_settings(), now=NOW)

    assert len(llm.calls) == 3  # 3 urinishdan keyin to'xtaydi
    async with sessionmaker() as session:
        post = (await session.execute(select(RawPost))).scalar_one()
    assert post.status == "failed"
    assert await _count(sessionmaker, AiCall) == 0


async def test_trust_score_uses_market_median_and_phone_reuse(sessionmaker: SessionMaker) -> None:
    async with sessionmaker() as session:
        channel = await make_channel(session)
        for price in (380, 400, 400, 420, 450):
            await make_raw_post(session, channel, NOW, text=rent_text() + f" narx {price}")
        # Shubhali: bozordan 50% arzon, rasmsiz
        await make_raw_post(session, channel, NOW, text=rent_text() + " arzon", has_photo=False)
        await session.commit()
    prices = [380, 400, 400, 420, 450, 200]
    llm = FakeLLM(lambda call: rent_data(price_amount=prices[len(llm.calls) - 1]))

    await process_pending(sessionmaker, llm, make_settings(), now=NOW)

    async with sessionmaker() as session:
        cheap = (
            await session.execute(select(Listing).where(Listing.price_usd == 200))
        ).scalar_one()
    assert cheap.trust_score == 35  # 100 - 50 (narx) - 15 (rasm yo'q)
    assert len(cheap.trust_reasons) == 2
    assert "50% past" in cheap.trust_reasons[0]


# ------------------------------------------------------------ kunlik AI limiti


async def test_daily_budget_stops_parsing_and_notifies_admin_once(
    sessionmaker: SessionMaker,
) -> None:
    """Qabul mezoni 5: kunlik limit oshsa tahlil to'xtaydi va admin'ga xabar ketadi."""
    settings = make_settings(daily_ai_budget_usd=Decimal("0.001"))  # 1000 mikro-dollar
    await _seed_posts(sessionmaker, 6)
    # Har chaqiruv: 4000 kirish tokeni * $0.10/MTok = 400 mikro-dollar
    llm = FakeLLM(
        lambda call: rent_data(price_amount=300 + 10 * len(llm.calls)),
        usage=TokenUsage(input_tokens=4000),
    )

    stats = await process_pending(sessionmaker, llm, settings, now=NOW)

    # 3-chaqiruvdan keyin 1200 >= 1000 — to'rtinchi post AI'ga yuborilmaydi
    assert stats.budget_stopped is True
    assert len(llm.calls) == 3
    assert await _count(sessionmaker, RawPost, RawPost.status == "new") == 3
    assert await _count(sessionmaker, AdminEvent) == 1
    async with sessionmaker() as session:
        event = (await session.execute(select(AdminEvent))).scalar_one()
    assert "Kunlik AI limiti tugadi" in event.text
    assert "$0.00" not in event.text.split("limit")[0]  # sarflangan summa ko'rsatilgan

    # Shu kuni qayta urinish: AI chaqirilmaydi, admin'ga ikkinchi xabar ketmaydi
    later = await process_pending(sessionmaker, llm, settings, now=NOW + timedelta(hours=3))
    assert later.budget_stopped is True
    assert len(llm.calls) == 3
    assert await _count(sessionmaker, AdminEvent) == 1

    # Ertasi kuni (Toshkent vaqti bilan) limit yangilanadi va tahlil davom etadi
    tomorrow = await process_pending(sessionmaker, llm, settings, now=NOW + timedelta(days=1))
    assert tomorrow.budget_stopped is False
    assert len(llm.calls) == 6
    assert await _count(sessionmaker, RawPost, RawPost.status == "new") == 0


async def test_chat_spend_counts_towards_daily_budget(sessionmaker: SessionMaker) -> None:
    settings = make_settings(daily_ai_budget_usd=Decimal("0.01"))
    await _seed_posts(sessionmaker, 1)
    async with sessionmaker() as session:
        session.add(
            AiCall(
                created_at=NOW - timedelta(hours=1),
                purpose="chat",
                model="claude-sonnet-5-5",
                input_tokens=0,
                output_tokens=0,
                cache_write_tokens=0,
                cache_read_tokens=0,
                cost_micro_usd=10_000,
            )
        )
        await session.commit()
    llm = FakeLLM()

    stats = await process_pending(sessionmaker, llm, settings, now=NOW)

    assert stats.budget_stopped is True
    assert llm.calls == []
