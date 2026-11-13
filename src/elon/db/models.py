from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from elon.db.base import Base, BigIntPK, UTCDateTime

# ---------------------------------------------------------------- yig'uvchi


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(255))
    tg_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    joined_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    join_attempted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    backfilled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_message_id: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(255))


class RawPost(Base):
    """Kanaldan olingan xom post. Toifadan mustaqil."""

    __tablename__ = "raw_posts"
    __table_args__ = (UniqueConstraint("channel_id", "message_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    message_id: Mapped[int]
    category: Mapped[str] = mapped_column(String(32))
    posted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    has_photo: Mapped[bool] = mapped_column(default=False)
    photo_fp: Mapped[str | None] = mapped_column(String(40))
    source_url: Mapped[str] = mapped_column(String(255))
    #: new | parsed | skipped | failed
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    skip_reason: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(default=0)


class Listing(Base):
    """Tahlil qilingan e'lon. Umumiy ustunlar + toifaga xos `attrs`."""

    __tablename__ = "listings"
    __table_args__ = (Index("ix_listings_segment_posted", "segment", "posted_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    raw_post_id: Mapped[int] = mapped_column(ForeignKey("raw_posts.id"), unique=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    source_url: Mapped[str] = mapped_column(String(255))
    posted_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    #: rent uchun — tuman
    location: Mapped[str | None] = mapped_column(String(64), index=True)
    #: bozor medianasi shu kalit bo'yicha hisoblanadi (rent: "tuman|xona")
    segment: Mapped[str | None] = mapped_column(String(96))
    price_usd: Mapped[int | None]
    price_original: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    summary: Mapped[str] = mapped_column(String(400))
    is_agent: Mapped[bool | None]
    #: e'lon egasi telefonining HMAC xeshi (raqamning o'zi saqlanmaydi)
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    has_photo: Mapped[bool] = mapped_column(default=False)
    photo_fp: Mapped[str | None] = mapped_column(String(40), index=True)
    deposit_requested: Mapped[bool | None]
    prepay_before_viewing: Mapped[bool | None]
    attrs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id"), index=True)
    trust_score: Mapped[int] = mapped_column(default=100)
    trust_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    notify_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)


# ---------------------------------------------------------------- foydalanuvchi


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    phone: Mapped[str] = mapped_column(String(20))
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime)
    trial_ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    paid_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expiry_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    #: collecting | confirm | done
    state: Mapped[str] = mapped_column(String(16), default="collecting")
    messages: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    filter: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SearchLog(Base):
    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filter: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    category: Mapped[str] = mapped_column(String(32))
    filter: Mapped[dict[str, Any]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "listing_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("user_id", "listing_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    #: +1 yoki -1
    value: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


# ---------------------------------------------------------------- AI va admin


class AiCall(Base):
    """Har bir AI chaqiruvi: tokenlar va narx (mikro-dollarda, 1 USD = 1 000 000)."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    #: parse | chat
    purpose: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    cache_write_tokens: Mapped[int]
    cache_read_tokens: Mapped[int]
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    raw_post_id: Mapped[int | None] = mapped_column(ForeignKey("raw_posts.id"))


class AdminEvent(Base):
    """Admin'ga yuboriladigan xabarlar navbati (collector ham yoza oladi, bot yuboradi)."""

    __tablename__ = "admin_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    dedup_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
