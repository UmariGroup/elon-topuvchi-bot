"""Sozlamalar. Hammasi muhit o'zgaruvchilaridan (.env) olinadi."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- majburiy (.env.example dagi nomlar) ---
    telegram_bot_token: SecretStr
    tg_api_id: int
    tg_api_hash: SecretStr
    tg_session_path: str = "/data/collector.session"
    anthropic_api_key: SecretStr
    #: ichida parol bor — SecretStr, repr/logda ko'rinmaydi
    database_url: SecretStr
    admin_ids: Annotated[list[int], NoDecode] = []
    trial_days: int = 7
    daily_ai_budget_usd: Decimal = Decimal("3")

    # --- ixtiyoriy, standart qiymatlari bor ---
    parser_model: str = "claude-haiku-5-5"
    chat_model: str = "claude-sonnet-5-5"
    #: so'mdagi narxlarni dollarga o'tkazish kursi (1 USD = N so'm)
    usd_uzs_rate: int = 12_700
    #: bitta foydalanuvchi kuniga nechta suhbat xabari yubora oladi (AI xarajatini cheklash)
    user_daily_message_limit: int = 40
    max_notifications_per_day: int = 10
    max_joins_per_day: int = 20
    backfill_days: int = 7
    poll_interval_seconds: int = 180
    #: qidiruvda necha kunlik e'lonlar ko'rsatiladi
    search_max_age_days: int = 14
    #: bundan past ishonch balli e'lon kuzatuv bildirishnomasiga yuborilmaydi
    min_notify_score: int = 40
    channels_file: str = "config/channels.yaml"
    #: e'lon egasi telefonini xeshlash kaliti; berilmasa TG_API_HASH ishlatiladi
    phone_hash_salt: SecretStr | None = None

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [int(part) for part in value.replace(";", ",").split(",") if part.strip()]
        if isinstance(value, int):
            return [value]
        return value

    @property
    def daily_budget_micro_usd(self) -> int:
        return int(self.daily_ai_budget_usd * 1_000_000)

    @property
    def phone_hash_key(self) -> bytes:
        secret = self.phone_hash_salt or self.tg_api_hash
        return secret.get_secret_value().encode()


@lru_cache
def get_settings() -> Settings:
    return Settings()
