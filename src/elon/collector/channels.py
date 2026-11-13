"""config/channels.yaml ni o'qish va bazadagi kanallar ro'yxati bilan sinxronlash."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elon.db.models import Channel

_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


@dataclass(frozen=True)
class ChannelSpec:
    username: str
    category: str
    enabled: bool = True


def parse_username(value: str) -> str:
    """`@name`, `t.me/name`, `https://t.me/name` -> `name`."""
    name = value.strip()
    name = re.sub(r"^(https?://)?t\.me/(s/)?", "", name).lstrip("@").split("/")[0]
    if not _USERNAME.match(name):
        raise ValueError(f"kanal nomi noto'g'ri: {value!r}")
    return name


def load_channels(path: str | Path) -> list[ChannelSpec]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    specs: dict[str, ChannelSpec] = {}
    for item in data.get("channels") or []:
        if isinstance(item, str):
            item = {"username": item}
        username = parse_username(str(item["username"]))
        specs[username.lower()] = ChannelSpec(
            username=username,
            category=str(item.get("category", "rent")),
            enabled=bool(item.get("enabled", True)),
        )
    return list(specs.values())


async def sync_channels(session: AsyncSession, specs: list[ChannelSpec]) -> int:
    """Fayldagi kanallarni bazaga qo'shadi/yangilaydi. Faylda yo'q kanallar o'chiriladi (enabled=False)."""
    existing = {
        channel.username.lower(): channel
        for channel in (await session.execute(select(Channel))).scalars()
    }
    wanted = {spec.username.lower() for spec in specs}
    added = 0
    for spec in specs:
        channel = existing.get(spec.username.lower())
        if channel is None:
            session.add(
                Channel(username=spec.username, category=spec.category, enabled=spec.enabled)
            )
            added += 1
        else:
            channel.category = spec.category
            # Avval xato bilan o'chirilgan kanal ham qayta sinab ko'riladi (har ishga tushishda)
            channel.enabled = spec.enabled
    for key, channel in existing.items():
        if key not in wanted:
            channel.enabled = False
    await session.flush()
    return added
