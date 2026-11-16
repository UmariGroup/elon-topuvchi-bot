from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    """Bitta xavf belgisi: kod, jarima bali va foydalanuvchiga ko'rsatiladigan sabab."""

    code: str
    penalty: int
    reason: str
