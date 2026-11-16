"""Botning to'liq yo'li — haqiqiy aiogram Dispatcher orqali, soxta Telegram sessiyasi bilan.

/start -> telefon -> suhbat -> 5 natija -> 👍 -> kuzatuv -> yangi e'lon bildirishnomasi
-> sinov tugashi -> /activate -> /stats -> /delete_me

Telegram serveriga so'rov ketmaydi: bot yuborgan har bir so'rov `FakeTelegram.requests`
ga yoziladi. Claude o'rnida `FakeLLM`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message
from sqlalchemy import select

from elon.bot import texts
from elon.bot.background import tick
from elon.bot.main import build_dispatcher
from elon.db.models import (
    AdminEvent,
    Conversation,
    Feedback,
    Notification,
    SearchLog,
    User,
    Watch,
)
from elon.db.session import SessionMaker
from elon.timeutil import utcnow
from tests.conftest import FakeLLM, make_settings
from tests.factories import make_channel, make_listing

USER_ID = 111
ADMIN_ID = 999
STRANGER_ID = 555


class FakeTelegram(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None
    ) -> TelegramType:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            message = Message(
                message_id=len(self.requests),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
            return message  # type: ignore[return-value]
        return True  # type: ignore[return-value]

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    def take(self) -> list[SendMessage]:
        """Oxirgi chaqiruvdan beri yuborilgan xabarlar."""
        sent = [request for request in self.requests if isinstance(request, SendMessage)]
        self.requests.clear()
        return sent


class Harness:
    def __init__(self, sessionmaker: SessionMaker) -> None:
        self.settings = make_settings()
        self.sessionmaker = sessionmaker
        self.telegram = FakeTelegram()
        self.llm = FakeLLM()
        self.bot = Bot("123456:TEST-token", session=self.telegram)
        self.dispatcher: Dispatcher = build_dispatcher(self.settings, sessionmaker, self.llm)
        self._update_id = 0

    def _base(self, user_id: int) -> dict[str, Any]:
        return {
            "message_id": self._update_id,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
        }

    async def _feed(self, payload: dict[str, Any]) -> list[SendMessage]:
        self._update_id += 1
        await self.dispatcher.feed_raw_update(self.bot, {"update_id": self._update_id, **payload})
        return self.telegram.take()

    async def text(self, user_id: int, text: str) -> list[SendMessage]:
        return await self._feed({"message": {**self._base(user_id), "text": text}})

    async def contact(self, user_id: int, owner_id: int, phone: str) -> list[SendMessage]:
        contact = {"phone_number": phone, "first_name": "Test", "user_id": owner_id}
        return await self._feed({"message": {**self._base(user_id), "contact": contact}})

    async def click(self, user_id: int, data: str) -> list[SendMessage]:
        callback = {
            "id": str(self._update_id),
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "chat_instance": "test",
            "data": data,
            "message": {**self._base(user_id), "text": "tugmali xabar"},
        }
        return await self._feed({"callback_query": callback})

    async def background(self, now: datetime | None = None) -> list[SendMessage]:
        await tick(self.bot, self.sessionmaker, self.settings, now or utcnow())
        return self.telegram.take()


def _buttons(message: SendMessage) -> list[str]:
    markup = message.reply_markup
    rows = getattr(markup, "inline_keyboard", None)
    assert rows is not None, "inline tugmalar yo'q"
    return [button.callback_data for row in rows for button in row]


def _chat_reply(message: str, ready: bool, **flt: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "districts": [],
        "rooms": [],
        "price_max_usd": None,
        "rental_type": "kvartira",
    }
    base.update(flt)
    return {"message": message, "ready": ready, "filter": base}


async def test_full_user_journey(sessionmaker: SessionMaker) -> None:
    h = Harness(sessionmaker)

    # 1. /start — telefon so'raladi ("Kontaktni ulashish" tugmasi)
    (asked,) = await h.text(USER_ID, "/start")
    assert asked.text == texts.ASK_CONTACT
    keyboard = getattr(asked.reply_markup, "keyboard", None)
    assert keyboard is not None and keyboard[0][0].request_contact is True

    # Ro'yxatdan o'tmasdan yozsa — yana telefon so'raladi, AI chaqirilmaydi
    (asked_again,) = await h.text(USER_ID, "Chilonzorda kvartira kerak")
    assert asked_again.text == texts.ASK_CONTACT
    assert h.llm.calls == []

    # Birovning kontakti qabul qilinmaydi
    (rejected,) = await h.contact(USER_ID, owner_id=777, phone="+998900000000")
    assert rejected.text == texts.OWN_CONTACT_ONLY

    # 2. O'z kontakti — ro'yxatdan o'tadi, 7 kunlik sinov boshlanadi
    (welcome,) = await h.contact(USER_ID, owner_id=USER_ID, phone="+998901112233")
    assert "7 kunlik bepul sinov" in (welcome.text or "")
    async with sessionmaker() as session:
        user = (await session.execute(select(User))).scalar_one()
    assert (user.tg_id, user.phone) == (USER_ID, "+998901112233")
    assert timedelta(days=6, hours=23) < user.trial_ends_at - utcnow() <= timedelta(days=7)

    # 3. Suhbat: birinchi xabar — bot aniqlashtiruvchi savol beradi
    h.llm.queue.append(
        _chat_reply("Byudjetingiz qancha?", False, districts=["chilonzor"], rooms=[2])
    )
    (question,) = await h.text(USER_ID, "Chilonzorda 2 xonali, oilaga")
    assert question.text == "Byudjetingiz qancha?"

    # Ikkinchi xabar — filtr tayyor, tasdiqlash tugmalari chiqadi
    h.llm.queue.append(
        _chat_reply(
            "Tushundim, filtrni tekshirib bering.",
            True,
            districts=["chilonzor"],
            rooms=[2],
            price_max_usd=400,
            for_whom="oila",
        )
    )
    reply, confirm = await h.text(USER_ID, "400$ gacha")
    assert reply.text == "Tushundim, filtrni tekshirib bering."
    assert "Chilonzor" in (confirm.text or "") and "400$ gacha" in (confirm.text or "")
    assert _buttons(confirm) == ["f:ok", "f:edit"]
    assert len(h.llm.calls) == 2

    # 4. Bazada 7 ta mos va 2 ta mos emas e'lon bor; tasdiqlash -> eng yaxshi 5 tasi
    now = utcnow()
    async with sessionmaker() as session:
        channel = await make_channel(session, "ijara_kanal")
        matching = [
            await make_listing(
                session, channel, now, price_usd=350 + 5 * i, posted_at=now - timedelta(hours=i + 1)
            )
            for i in range(7)
        ]
        await make_listing(session, channel, now, location="sergeli")
        await make_listing(session, channel, now, price_usd=700)
        await session.commit()

    results = await h.click(USER_ID, "f:ok")
    listings, footer, watch_question = results[:5], results[5], results[6]
    assert len(results) == 7
    for message, listing in zip(listings, matching[:5], strict=True):
        text = message.text or ""
        assert f"🔗 Manba: https://t.me/ijara_kanal/{listing.source_url.rsplit('/', 1)[1]}" in text
        assert "Ishonch balli: 100/100" in text
        assert f"{listing.price_usd}$ / oy" in text
        assert "+998" not in text  # e'lon egasining telefoni ko'rsatilmaydi
        assert _buttons(message) == [f"fb:{listing.id}:1", f"fb:{listing.id}:-1"]
    assert footer.text == texts.RESULTS_FOOTER
    assert watch_question.text == texts.WATCH_QUESTION
    assert _buttons(watch_question) == ["w:yes", "w:no"]
    async with sessionmaker() as session:
        log = (await session.execute(select(SearchLog))).scalar_one()
    assert log.result_count == 5

    # 5. 👍 bosiladi
    assert await h.click(USER_ID, f"fb:{matching[0].id}:1") == []
    async with sessionmaker() as session:
        feedback = (await session.execute(select(Feedback))).scalar_one()
    assert (feedback.listing_id, feedback.value) == (matching[0].id, 1)

    # 6. Kuzatuv yoqiladi
    (watch_on,) = await h.click(USER_ID, "w:yes")
    assert "Kuzatuv yoqildi" in (watch_on.text or "")
    async with sessionmaker() as session:
        watch = (await session.execute(select(Watch))).scalar_one()
    assert watch.active and watch.filter["price_max_usd"] == 400

    # Kuzatuv yoqilishidan oldin bazada bo'lgan e'lonlar qayta yuborilmaydi
    assert await h.background() == []

    # 7. Yangi mos e'lon tushadi -> darhol bildirishnoma
    async with sessionmaker() as session:
        fresh_channel = await make_channel(session, "yangi_kanal")
        fresh = await make_listing(session, fresh_channel, utcnow(), price_usd=390)
        await make_listing(session, fresh_channel, utcnow(), price_usd=900)  # mos emas
        await session.commit()
    (notification,) = await h.background()
    assert notification.chat_id == USER_ID
    assert (notification.text or "").startswith("🔔 Yangi mos e'lon")
    assert fresh.source_url in (notification.text or "")
    assert _buttons(notification) == [f"fb:{fresh.id}:1", f"fb:{fresh.id}:-1"]
    assert await h.background() == []  # ikkinchi marta yuborilmaydi
    async with sessionmaker() as session:
        sent = (await session.execute(select(Notification))).scalar_one()
    assert sent.listing_id == fresh.id

    # 8. Sinov muddati tugaydi -> foydalanuvchiga to'lov xabari, admin'ga bildirishnoma
    async with sessionmaker() as session:
        row = (await session.execute(select(User))).scalar_one()
        row.trial_ends_at = utcnow() - timedelta(minutes=1)
        await session.commit()
    expiry_messages = await h.background()
    by_chat = {message.chat_id: message.text or "" for message in expiry_messages}
    assert by_chat[USER_ID] == texts.PAYMENT
    assert f"/activate {USER_ID} 7" in by_chat[ADMIN_ID]
    assert await h.background() == []  # bir marta
    async with sessionmaker() as session:
        event = (await session.execute(select(AdminEvent))).scalar_one()
    assert event.sent_at is not None

    # Muddati tugagach bot ishlamaydi: AI chaqirilmaydi, to'lov xabari chiqadi
    calls_before = len(h.llm.calls)
    (blocked,) = await h.text(USER_ID, "Yunusobodda ham qarang")
    assert blocked.text == texts.PAYMENT
    (blocked_search,) = await h.click(USER_ID, "f:ok")
    assert blocked_search.text == texts.PAYMENT
    assert len(h.llm.calls) == calls_before

    # 9. /activate — faqat admin
    (denied,) = await h.text(STRANGER_ID, f"/activate {USER_ID} 30")
    assert denied.text == texts.UNKNOWN_COMMAND
    (usage,) = await h.text(ADMIN_ID, "/activate abc")
    assert usage.text == texts.ADMIN_ACTIVATE_USAGE
    (not_found,) = await h.text(ADMIN_ID, "/activate 424242 7")
    assert not_found.text == texts.ADMIN_USER_NOT_FOUND

    activation = await h.text(ADMIN_ID, f"/activate {USER_ID} 7")
    by_chat = {message.chat_id: message.text or "" for message in activation}
    assert by_chat[ADMIN_ID].startswith(f"✅ {USER_ID}: 7 kun qo'shildi")
    assert "7 kunga faollashtirildi" in by_chat[USER_ID]

    # Faollashtirilgach suhbat yana ishlaydi
    h.llm.queue.append(_chat_reply("Yunusobodni ham qo'shdim.", False, districts=["chilonzor"]))
    (resumed,) = await h.text(USER_ID, "Yunusobodda ham qarang")
    assert resumed.text == "Yunusobodni ham qo'shdim."

    # 10. /stats — faqat admin
    (denied_stats,) = await h.text(USER_ID, "/stats")
    assert denied_stats.text == texts.UNKNOWN_COMMAND
    (stats,) = await h.text(ADMIN_ID, "/stats")
    assert "Ro'yxatdan o'tganlar: 1" in (stats.text or "")
    assert "So'rovlar: jami 1" in (stats.text or "")
    assert "👍 1 / 👎 0" in (stats.text or "")

    # 11. /stop va /delete_me
    (stopped,) = await h.text(USER_ID, "/stop")
    assert stopped.text == texts.WATCH_OFF
    (ask_delete,) = await h.text(USER_ID, "/delete_me")
    assert _buttons(ask_delete) == ["del:yes", "del:no"]
    (deleted,) = await h.click(USER_ID, "del:yes")
    assert deleted.text == texts.DELETED
    async with sessionmaker() as session:
        for model in (User, Conversation, Watch, Feedback, Notification, SearchLog):
            assert list((await session.execute(select(model))).scalars()) == [], model.__name__

    # O'chirilgach /start yana telefon so'raydi
    (fresh_start,) = await h.text(USER_ID, "/start")
    assert fresh_start.text == texts.ASK_CONTACT

    await h.bot.session.close()


async def test_no_results_still_offers_watch(sessionmaker: SessionMaker) -> None:
    h = Harness(sessionmaker)
    await h.contact(USER_ID, owner_id=USER_ID, phone="+998901112233")
    h.llm.queue.append(_chat_reply("Tushundim.", True, districts=["bektemir"], rooms=[4]))
    await h.text(USER_ID, "Bektemirda 4 xonali")

    empty, watch_question = await h.click(USER_ID, "f:ok")

    assert empty.text == texts.NO_RESULTS
    assert watch_question.text == texts.WATCH_QUESTION


async def test_filter_edit_and_ai_failure(sessionmaker: SessionMaker) -> None:
    h = Harness(sessionmaker)
    await h.contact(USER_ID, owner_id=USER_ID, phone="+998901112233")

    # Filtrsiz "qidir" bosilsa
    (no_filter,) = await h.click(USER_ID, "f:ok")
    assert no_filter.text == texts.NO_FILTER

    (edit,) = await h.click(USER_ID, "f:edit")
    assert edit.text == texts.EDIT_PROMPT

    # AI xatosi foydalanuvchiga tushunarli xabar bilan qaytadi
    h.llm.queue.append(RuntimeError("API ishlamayapti"))
    (error,) = await h.text(USER_ID, "Sergelida 1 xonali")
    assert error.text == texts.AI_ERROR


async def test_help_and_group_chats_are_ignored(sessionmaker: SessionMaker) -> None:
    h = Harness(sessionmaker)
    (help_message,) = await h.text(USER_ID, "/help")
    assert "/delete_me" in (help_message.text or "")
    assert "7 kun bepul" in (help_message.text or "")

    # Guruhdagi xabarlarga bot javob bermaydi
    h._update_id += 1
    await h.dispatcher.feed_raw_update(
        h.bot,
        {
            "update_id": h._update_id,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": -100, "type": "supergroup", "title": "Guruh"},
                "from": {"id": USER_ID, "is_bot": False, "first_name": "Test"},
                "text": "/start",
            },
        },
    )
    assert h.telegram.take() == []
