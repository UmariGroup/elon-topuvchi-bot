"""Xizmatlar: foydalanuvchi, suhbat, qidiruv, kuzatuv, statistika."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from elon.categories.rent.filter import RentFilter
from elon.db.models import (
    AdminEvent,
    AiCall,
    Conversation,
    Feedback,
    Notification,
    SearchLog,
    User,
    Watch,
)
from elon.db.session import SessionMaker
from elon.services import users as user_service
from elon.services.chat import DailyLimitReached, handle_message
from elon.services.search import run_search
from elon.services.stats import collect_stats
from elon.services.users import Access, access_of
from elon.services.watches import notify_tick, save_feedback, set_watch, stop_watch
from tests.conftest import NOW, FakeLLM, make_settings
from tests.factories import make_channel, make_listing

FILTER = {
    "districts": ["chilonzor"],
    "rooms": [2],
    "price_max_usd": 450,
    "rental_type": "kvartira",
}


async def _user(sessionmaker: SessionMaker, tg_id: int = 111) -> User:
    async with sessionmaker() as session:
        user, _ = await user_service.register(
            session, tg_id=tg_id, phone="+998901112233", now=NOW, trial_days=7
        )
        await session.commit()
        return user


# ------------------------------------------------------------ foydalanuvchi


async def test_register_starts_trial_and_is_idempotent(sessionmaker: SessionMaker) -> None:
    async with sessionmaker() as session:
        user, created = await user_service.register(
            session, tg_id=1, phone="+998901112233", now=NOW, trial_days=7
        )
        again, created_again = await user_service.register(
            session, tg_id=1, phone="+998000000000", now=NOW + timedelta(days=5), trial_days=7
        )
    assert created and not created_again
    assert again.id == user.id
    assert user.trial_ends_at == NOW + timedelta(days=7)  # qayta /start sinovni uzaytirmaydi
    assert access_of(user, NOW + timedelta(days=6, hours=23)) is Access.TRIAL
    assert access_of(user, NOW + timedelta(days=7)) is Access.EXPIRED


async def test_expire_tick_notifies_once_and_activate_restores(sessionmaker: SessionMaker) -> None:
    await _user(sessionmaker)
    after_trial = NOW + timedelta(days=7, minutes=1)
    async with sessionmaker() as session:
        assert await user_service.expire_tick(session, NOW + timedelta(days=6)) == []
        expired = await user_service.expire_tick(session, after_trial)
        assert [user.tg_id for user in expired] == [111]
        assert await user_service.expire_tick(session, after_trial) == []  # ikkinchi marta emas
        events = list((await session.execute(select(AdminEvent))).scalars())
        assert len(events) == 1
        assert "/activate 111 7" in events[0].text
        assert "+998" not in events[0].text  # admin xabarida telefon yo'q

        user = await user_service.activate(session, tg_id=111, days=30, now=after_trial)
        assert user is not None
        assert access_of(user, after_trial) is Access.PAID
        assert user.paid_until == after_trial + timedelta(days=30)
        # Amaldagi obuna ustiga qo'shiladi
        await user_service.activate(session, tg_id=111, days=7, now=after_trial + timedelta(days=1))
        assert user.paid_until == after_trial + timedelta(days=37)
        # Obuna tugaganda yana xabar beriladi
        later = await user_service.expire_tick(session, after_trial + timedelta(days=38))
        assert [u.tg_id for u in later] == [111]
        assert await user_service.activate(session, tg_id=404, days=7, now=NOW) is None


async def test_delete_me_removes_all_personal_data(sessionmaker: SessionMaker) -> None:
    user = await _user(sessionmaker)
    other = await _user(sessionmaker, tg_id=222)
    async with sessionmaker() as session:
        channel = await make_channel(session)
        listing = await make_listing(session, channel, NOW)
        for owner in (user, other):
            session.add(
                Conversation(
                    user_id=owner.id,
                    messages=[{"role": "user", "content": "maxfiy"}],
                    filter=FILTER,
                    updated_at=NOW,
                )
            )
            session.add(SearchLog(user_id=owner.id, filter=FILTER, result_count=1, created_at=NOW))
            session.add(Notification(user_id=owner.id, listing_id=listing.id, sent_at=NOW))
            await set_watch(session, owner, RentFilter.model_validate(FILTER), NOW)
            await save_feedback(session, owner, listing.id, 1, NOW)
            session.add(
                AiCall(
                    created_at=NOW,
                    purpose="chat",
                    model="claude-sonnet-5-5",
                    input_tokens=1,
                    output_tokens=1,
                    cache_write_tokens=0,
                    cache_read_tokens=0,
                    cost_micro_usd=12,
                    user_id=owner.id,
                )
            )
        await session.commit()

        assert await user_service.delete_user(session, 111) is True
        await session.commit()
        assert await user_service.delete_user(session, 111) is False

        for model in (Conversation, SearchLog, Notification, Watch, Feedback):
            rows = list((await session.execute(select(model))).scalars())
            owners = [row.user_id for row in rows]  # type: ignore[attr-defined]
            assert owners == [other.id], model.__name__
        users = list((await session.execute(select(User))).scalars())
        assert [u.tg_id for u in users] == [222]
        # Xarajat yozuvi qoladi, lekin shaxsga bog'lanmagan
        calls = list((await session.execute(select(AiCall).order_by(AiCall.id))).scalars())
        assert [call.user_id for call in calls] == [None, other.id]


# ------------------------------------------------------------ suhbat


def _reply(message: str, ready: bool, **flt: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "districts": [],
        "rooms": [],
        "price_max_usd": None,
        "rental_type": "kvartira",
    }
    base.update(flt)
    return {"message": message, "ready": ready, "filter": base}


async def test_chat_collects_filter_over_two_turns(sessionmaker: SessionMaker) -> None:
    settings = make_settings()
    user = await _user(sessionmaker)
    llm = FakeLLM()
    llm.queue = [
        _reply("Byudjetingiz qancha?", False, districts=["chilonzor"], rooms=[2]),
        _reply("Tushundim.", True, districts=["chilonzor"], rooms=[2], price_max_usd=400),
    ]
    async with sessionmaker() as session:
        first = await handle_message(session, llm, settings, user, "Chilonzorda 2 xonali", NOW)
        second = await handle_message(session, llm, settings, user, "400$ gacha", NOW)
        await session.commit()
        conversation = (await session.execute(select(Conversation))).scalar_one()
        calls = list((await session.execute(select(AiCall))).scalars())

    assert (first.message, first.ready) == ("Byudjetingiz qancha?", False)
    assert second.ready is True
    assert second.filter.price_max_usd == 400
    assert conversation.state == "confirm"
    assert conversation.filter is not None and conversation.filter["districts"] == ["chilonzor"]
    assert [m["role"] for m in conversation.messages] == ["user", "assistant", "user", "assistant"]

    # Model: Sonnet; ikkinchi chaqiruvda tarix va joriy filtr uzatilgan
    assert {call["model"] for call in llm.calls} == {"claude-sonnet-5-5"}
    second_messages = llm.calls[1]["messages"]
    assert [m["role"] for m in second_messages] == ["user", "assistant", "user"]
    assert '"districts": ["chilonzor"]' in second_messages[-1]["content"]
    assert "<kurs>1 USD = 12700 so'm</kurs>" in second_messages[-1]["content"]
    # Xarajat foydalanuvchiga bog'lab yozilgan
    assert [(call.purpose, call.user_id) for call in calls] == [("chat", user.id)] * 2


async def test_chat_survives_malformed_model_output(sessionmaker: SessionMaker) -> None:
    user = await _user(sessionmaker)
    llm = FakeLLM()
    llm.queue = [{"message": "", "ready": True, "filter": {"rental_type": "saroy"}}]
    async with sessionmaker() as session:
        reply = await handle_message(session, llm, make_settings(), user, "salom", NOW)
    assert reply.ready is False
    assert reply.message  # zaxira matn
    assert reply.filter == RentFilter()


async def test_chat_daily_message_limit(sessionmaker: SessionMaker) -> None:
    settings = make_settings(user_daily_message_limit=2)
    user = await _user(sessionmaker)
    llm = FakeLLM(lambda call: _reply("Davom eting", False))
    async with sessionmaker() as session:
        await handle_message(session, llm, settings, user, "bir", NOW)
        await handle_message(session, llm, settings, user, "ikki", NOW)
        with pytest.raises(DailyLimitReached):
            await handle_message(session, llm, settings, user, "uch", NOW)
        assert len(llm.calls) == 2
        # Ertasi kuni yana yozish mumkin
        await handle_message(session, llm, settings, user, "to'rt", NOW + timedelta(days=1))
    assert len(llm.calls) == 3


# ------------------------------------------------------------ qidiruv


async def test_search_returns_top_five_matching_by_trust_and_freshness(
    sessionmaker: SessionMaker,
) -> None:
    settings = make_settings()
    user = await _user(sessionmaker)
    async with sessionmaker() as session:
        channel = await make_channel(session)
        good = [
            await make_listing(
                session, channel, NOW, price_usd=390 + i, posted_at=NOW - timedelta(hours=i)
            )
            for i in range(6)
        ]
        risky = await make_listing(
            session, channel, NOW, price_usd=380, has_photo=False, prepay_before_viewing=True
        )
        # Mos kelmaydiganlar
        await make_listing(session, channel, NOW, location="yunusobod")
        await make_listing(session, channel, NOW, price_usd=600)
        await make_listing(session, channel, NOW, attrs={"rooms": 3})
        await make_listing(session, channel, NOW, posted_at=NOW - timedelta(days=20))
        duplicate = await make_listing(session, channel, NOW, duplicate_of_id=good[0].id)
        await session.commit()

        found = await run_search(session, settings, user, RentFilter.model_validate(FILTER), NOW)
        await session.commit()
        logs = list((await session.execute(select(SearchLog))).scalars())

    assert [listing.id for listing in found] == [listing.id for listing in good[:5]]
    assert risky.id not in {listing.id for listing in found}
    assert duplicate.id not in {listing.id for listing in found}
    assert risky.trust_score == 40  # qidiruvda ball qayta hisoblandi: -45 (oldindan pul) -15 (rasm)
    assert [(log.user_id, log.result_count) for log in logs] == [(user.id, 5)]


async def test_search_with_no_matches_is_logged(sessionmaker: SessionMaker) -> None:
    user = await _user(sessionmaker)
    async with sessionmaker() as session:
        found = await run_search(
            session, make_settings(), user, RentFilter(districts=["bektemir"]), NOW
        )
        count = (await session.execute(select(func.count()).select_from(SearchLog))).scalar_one()
    assert found == []
    assert count == 1


# ------------------------------------------------------------ kuzatuv


class Outbox:
    def __init__(self, blocked: set[int] | None = None) -> None:
        self.sent: list[tuple[int, str, int]] = []
        self.blocked = blocked or set()

    async def __call__(self, tg_id: int, text: str, listing_id: int) -> bool:
        if tg_id in self.blocked:
            return False
        self.sent.append((tg_id, text, listing_id))
        return True


async def test_watch_sends_new_matching_listing_once(sessionmaker: SessionMaker) -> None:
    settings = make_settings()
    user = await _user(sessionmaker)
    outbox = Outbox()
    async with sessionmaker() as session:
        channel = await make_channel(session)
        await set_watch(session, user, RentFilter.model_validate(FILTER), NOW)
        match = await make_listing(session, channel, NOW)
        await make_listing(session, channel, NOW, location="sergeli")  # mos emas
        await make_listing(
            session, channel, NOW, posted_at=NOW - timedelta(days=3)
        )  # eski (backfill)
        await make_listing(session, channel, NOW, trust_score=20)  # ishonchsiz
        await make_listing(session, channel, NOW, duplicate_of_id=match.id)  # dublikat
        await session.commit()

        assert await notify_tick(session, settings, outbox, NOW) == 1
        assert await notify_tick(session, settings, outbox, NOW) == 0  # qayta yuborilmaydi
        await session.commit()

    assert [(tg_id, listing_id) for tg_id, _, listing_id in outbox.sent] == [(111, match.id)]
    text = outbox.sent[0][1]
    assert text.startswith("🔔 Yangi mos e'lon")
    assert match.source_url in text


async def test_watch_daily_cap_expired_and_blocked_users(sessionmaker: SessionMaker) -> None:
    settings = make_settings(max_notifications_per_day=10)
    active = await _user(sessionmaker, tg_id=111)
    blocked = await _user(sessionmaker, tg_id=222)
    expired = await _user(sessionmaker, tg_id=333)
    outbox = Outbox(blocked={222})
    moment = NOW + timedelta(hours=1)
    async with sessionmaker() as session:
        channel = await make_channel(session)
        for user in (active, blocked, expired):
            await set_watch(session, user, RentFilter.model_validate(FILTER), NOW)
        (await session.get(User, expired.id)).trial_ends_at = NOW  # type: ignore[union-attr]
        for _ in range(13):
            await make_listing(session, channel, moment)
        await session.commit()

        delivered = await notify_tick(session, settings, outbox, moment)
        await session.commit()
        watches = {w.user_id: w for w in (await session.execute(select(Watch))).scalars()}

        assert delivered == 10  # kuniga 10 tadan oshmaydi
        assert {tg_id for tg_id, _, _ in outbox.sent} == {111}
        assert watches[blocked.id].active is False  # botni bloklagan — kuzatuv o'chadi
        assert watches[expired.id].active is True  # muddati tugagan — yuborilmaydi, lekin saqlanadi

        # Ertasi kuni limit yangilanadi
        await make_listing(session, channel, moment + timedelta(days=1))
        await session.commit()
        assert await notify_tick(session, settings, outbox, moment + timedelta(days=1)) == 1

        assert await stop_watch(session, active) is True
        assert await stop_watch(session, active) is False


async def test_feedback_keeps_latest_vote(sessionmaker: SessionMaker) -> None:
    user = await _user(sessionmaker)
    async with sessionmaker() as session:
        channel = await make_channel(session)
        listing = await make_listing(session, channel, NOW)
        await save_feedback(session, user, listing.id, 1, NOW)
        await save_feedback(session, user, listing.id, -1, NOW)
        await session.commit()
        votes = list((await session.execute(select(Feedback.value))).scalars())
    assert votes == [-1]


# ------------------------------------------------------------ statistika


async def test_stats(sessionmaker: SessionMaker) -> None:
    trial = await _user(sessionmaker, tg_id=1)
    paid = await _user(sessionmaker, tg_id=2)
    await _user(sessionmaker, tg_id=3)
    moment = NOW + timedelta(days=8)  # hammaning sinovi tugagan
    async with sessionmaker() as session:
        await user_service.activate(session, tg_id=paid.tg_id, days=30, now=moment)
        channel = await make_channel(session)
        listing = await make_listing(session, channel, moment)
        await make_listing(session, channel, moment, duplicate_of_id=listing.id)
        session.add(SearchLog(user_id=trial.id, filter=FILTER, result_count=3, created_at=moment))
        session.add(SearchLog(user_id=trial.id, filter=FILTER, result_count=0, created_at=NOW))
        await save_feedback(session, trial, listing.id, 1, moment)
        await save_feedback(session, paid, listing.id, -1, moment)
        for cost, created in ((2_500_000, moment), (1_250_000, NOW)):
            session.add(
                AiCall(
                    created_at=created,
                    purpose="parse",
                    model="claude-haiku-5-5",
                    input_tokens=250,
                    output_tokens=10,
                    cache_write_tokens=0,
                    cache_read_tokens=750,
                    cost_micro_usd=cost,
                )
            )
        await session.commit()
        stats = await collect_stats(session, moment)

    assert (stats.registered, stats.active) == (3, 1)
    assert (stats.trial_ended, stats.trial_ended_paid) == (3, 1)
    assert (stats.searches_total, stats.searches_today) == (2, 1)
    assert (stats.likes, stats.dislikes) == (1, 1)
    assert (stats.ai_cost_today_usd, stats.ai_cost_total_usd) == (2.5, 3.75)
    assert stats.ai_cache_read_share == 0.75
    assert (stats.posts_total, stats.listings_unique) == (2, 1)
    text = stats.format()
    assert "Ro'yxatdan o'tganlar: 3" in text
    assert "50% ijobiy" in text
    assert "bugun $2.50, jami $3.75" in text
