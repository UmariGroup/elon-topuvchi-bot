"""Yig'uvchi mantiqi soxta manba bilan (real Telegram'siz)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from elon.collector.channels import load_channels, parse_username, sync_channels
from elon.collector.service import (
    ChannelInfo,
    ChannelUnavailable,
    join_next,
    poll_channel,
)
from elon.collector.telegram import to_post
from elon.db.models import Channel, RawPost
from elon.db.session import SessionMaker
from elon.pipeline.ingest import PostData, store_post
from tests.conftest import NOW
from tests.factories import make_channel, rent_text

REPO = Path(__file__).resolve().parent.parent


class FakeSource:
    def __init__(self, posts: list[PostData] | None = None, *, joined: bool = False) -> None:
        self.posts = posts or []
        self.joined = joined
        self.fetch_calls: list[dict[str, object]] = []
        self.join_calls: list[str] = []
        self.unavailable: set[str] = set()

    async def resolve(self, username: str) -> ChannelInfo:
        return ChannelInfo(tg_id=-1001234567890, title="Test kanal", joined=self.joined)

    async def fetch(
        self, username: str, *, min_id: int = 0, since: datetime | None = None
    ) -> list[PostData]:
        self.fetch_calls.append({"min_id": min_id, "since": since})
        return [
            post
            for post in self.posts
            if post.message_id > min_id and (since is None or post.posted_at >= since)
        ]

    async def join(self, username: str) -> None:
        self.join_calls.append(username)
        if username in self.unavailable:
            raise ChannelUnavailable("ChannelPrivateError")


def _post(message_id: int, days_ago: float = 0, text: str | None = None) -> PostData:
    return PostData(
        message_id=message_id,
        posted_at=NOW - timedelta(days=days_ago),
        text=rent_text(message_id) if text is None else text,
        has_photo=True,
        photo_fp="fp",
    )


# ------------------------------------------------------------ channels.yaml


@pytest.mark.parametrize(
    "value", ["arentash", "@arentash", "t.me/arentash", "https://t.me/s/arentash/55"]
)
def test_parse_username(value: str) -> None:
    assert parse_username(value) == "arentash"


def test_parse_username_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="noto'g'ri"):
        parse_username("t.me/+AbCdEf")


def test_load_channels(tmp_path: Path) -> None:
    path = tmp_path / "channels.yaml"
    path.write_text(
        "channels:\n"
        "  - username: '@kanal_bir'\n"
        "  - username: kanal_ikki\n    enabled: false\n"
        "  - kanal_uch\n"
        "  - username: Kanal_Bir\n    category: rent\n",
        encoding="utf-8",
    )
    specs = load_channels(path)
    assert [(s.username, s.enabled) for s in specs] == [
        ("Kanal_Bir", True),
        ("kanal_ikki", False),
        ("kanal_uch", True),
    ]


def test_repo_channel_list_is_valid() -> None:
    specs = load_channels(REPO / "config" / "channels.yaml")
    assert len(specs) >= 10
    assert all(spec.category == "rent" for spec in specs)


async def test_sync_channels_adds_and_disables(sessionmaker: SessionMaker) -> None:
    async with sessionmaker() as session:
        await make_channel(session, "eski_kanal")
        specs = load_channels(REPO / "config" / "channels.yaml")
        added = await sync_channels(session, specs)
        await session.commit()
        channels = {c.username: c for c in (await session.execute(select(Channel))).scalars()}
    assert added == len(specs)
    assert channels["eski_kanal"].enabled is False
    assert all(channels[spec.username].enabled for spec in specs)


# ------------------------------------------------------------ o'qish


async def test_first_poll_backfills_last_seven_days(sessionmaker: SessionMaker) -> None:
    source = FakeSource([_post(1, days_ago=10), _post(2, days_ago=6), _post(3, days_ago=0.1)])
    async with sessionmaker() as session:
        channel = await make_channel(session, "kanal")
        stored = await poll_channel(session, source, channel, NOW, backfill_days=7)
        await session.commit()
        posts = list((await session.execute(select(RawPost).order_by(RawPost.id))).scalars())

    assert stored == 2
    assert source.fetch_calls == [{"min_id": 0, "since": NOW - timedelta(days=7)}]
    assert [post.message_id for post in posts] == [2, 3]
    assert posts[0].source_url == "https://t.me/kanal/2"
    assert posts[0].category == "rent" and posts[0].status == "new"
    assert posts[0].has_photo and posts[0].photo_fp == "fp"
    assert channel.tg_id == -1001234567890
    assert channel.backfilled_at == NOW
    assert channel.last_message_id == 3


async def test_next_poll_fetches_only_new_posts(sessionmaker: SessionMaker) -> None:
    source = FakeSource([_post(5), _post(6, text="  "), _post(7)])
    async with sessionmaker() as session:
        channel = await make_channel(
            session, "kanal", backfilled_at=NOW, last_message_id=5, tg_id=1
        )
        stored = await poll_channel(session, source, channel, NOW, backfill_days=7)
        again = await poll_channel(session, source, channel, NOW, backfill_days=7)
        await session.commit()

    assert source.fetch_calls[0] == {"min_id": 5, "since": None}
    assert stored == 1  # 6-post matnsiz (albom rasmi), 5 avval olingan
    assert again == 0
    assert channel.last_message_id == 7


async def test_quiet_channel_never_reads_from_the_beginning(sessionmaker: SessionMaker) -> None:
    """Backfill paytida post bo'lmagan kanal keyingi safar ham sana bo'yicha so'raladi."""
    source = FakeSource([_post(900, days_ago=400)])  # yagona post — bir yildan eski
    async with sessionmaker() as session:
        channel = await make_channel(session, "jim_kanal")
        await poll_channel(session, source, channel, NOW, backfill_days=7)
        later = NOW + timedelta(minutes=3)
        stored = await poll_channel(session, source, channel, later, backfill_days=7)

    assert stored == 0
    assert channel.last_message_id == 0
    assert source.fetch_calls[1] == {"min_id": 0, "since": later - timedelta(days=7)}


async def test_sync_reenables_channel_disabled_by_error(sessionmaker: SessionMaker) -> None:
    async with sessionmaker() as session:
        channel = await make_channel(session, "arentash", enabled=False, last_error="ValueError")
        await sync_channels(session, load_channels(REPO / "config" / "channels.yaml"))
    assert channel.enabled is True


async def test_store_post_is_idempotent(sessionmaker: SessionMaker) -> None:
    async with sessionmaker() as session:
        channel = await make_channel(session)
        first = await store_post(session, channel, _post(10), NOW)
        second = await store_post(session, channel, _post(10), NOW)
        await session.commit()
    assert first is not None
    assert second is None


async def test_already_joined_channel_is_marked(sessionmaker: SessionMaker) -> None:
    async with sessionmaker() as session:
        channel = await make_channel(session)
        await poll_channel(session, FakeSource(joined=True), channel, NOW, backfill_days=7)
    assert channel.joined_at == NOW


# ------------------------------------------------------------ a'zo bo'lish limiti


async def test_join_respects_daily_limit(sessionmaker: SessionMaker) -> None:
    source = FakeSource()
    async with sessionmaker() as session:
        for index in range(30):
            await make_channel(session, f"kanal_{index:02d}", tg_id=1000 + index)
        await session.commit()

        moment = NOW
        for _ in range(30):
            moment += timedelta(minutes=5)
            await join_next(session, source, moment, max_per_day=20)
            await session.commit()
        assert len(source.join_calls) == 20  # bir kunda 20 tadan oshmaydi

        # 24 soatdan keyin qolganlari
        moment = NOW + timedelta(days=1, hours=3)
        for _ in range(30):
            moment += timedelta(minutes=5)
            await join_next(session, source, moment, max_per_day=20)
            await session.commit()
    assert len(source.join_calls) == 30
    assert len(set(source.join_calls)) == 30


async def test_join_skips_unresolved_and_counts_failed_attempts(sessionmaker: SessionMaker) -> None:
    source = FakeSource()
    source.unavailable.add("yopiq_kanal")
    async with sessionmaker() as session:
        await make_channel(session, "hali_topilmagan")  # tg_id yo'q — avval poll qilinishi kerak
        closed = await make_channel(session, "yopiq_kanal", tg_id=5)
        await session.commit()

        first = await join_next(session, source, NOW, max_per_day=20)
        second = await join_next(session, source, NOW + timedelta(minutes=5), max_per_day=20)

    assert first is not None and first.username == "yopiq_kanal"
    assert closed.joined_at is None
    assert closed.join_attempted_at == NOW
    assert closed.last_error is not None
    assert second is None  # 3 kun ichida qayta urinmaydi


# ------------------------------------------------------------ Telethon xabari -> PostData


class _FakeMessage:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def test_to_post_handles_text_and_service_messages() -> None:
    post = to_post(_FakeMessage(id=7, message="Ijaraga kvartira", date=NOW, photo=None))
    assert post == PostData(message_id=7, posted_at=NOW, text="Ijaraga kvartira")
    assert to_post(_FakeMessage(id=8, date=NOW)) is None  # xizmat xabari (matn yo'q)


def test_to_post_with_real_telethon_message_and_photo() -> None:
    from telethon.tl import types
    from telethon.tl.custom.message import Message

    def photo(thumb: bytes) -> types.MessageMediaPhoto:
        return types.MessageMediaPhoto(
            photo=types.Photo(
                id=1,
                access_hash=1,
                file_reference=b"",
                date=NOW,
                dc_id=2,
                sizes=[
                    types.PhotoStrippedSize(type="i", bytes=thumb),
                    types.PhotoSize(type="x", w=800, h=600, size=1000),
                ],
            )
        )

    def message(thumb: bytes) -> Message:
        return Message(
            id=42, peer_id=types.PeerChannel(1), date=NOW, message="Ijaraga", media=photo(thumb)
        )

    first, same, other = (
        to_post(message(b"abc")),
        to_post(message(b"abc")),
        to_post(message(b"xyz")),
    )
    assert first is not None and same is not None and other is not None
    assert (first.message_id, first.text, first.has_photo) == (42, "Ijaraga", True)
    assert first.photo_fp is not None and len(first.photo_fp) == 40
    assert first.photo_fp == same.photo_fp  # bir xil rasm — bir xil iz
    assert first.photo_fp != other.photo_fp
