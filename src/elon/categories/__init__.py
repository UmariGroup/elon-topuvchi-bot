"""Toifalar reyestri. Yangi toifa shu yerga qo'shiladi."""

from __future__ import annotations

from elon.categories.base import Category, Extracted
from elon.categories.rent.extract import RENT

REGISTRY: dict[str, Category] = {RENT.name: RENT}


def get_category(name: str) -> Category | None:
    return REGISTRY.get(name)


__all__ = ["REGISTRY", "Category", "Extracted", "get_category"]
