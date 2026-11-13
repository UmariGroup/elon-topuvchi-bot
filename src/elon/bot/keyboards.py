from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from elon.bot import texts


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.CONTACT_BUTTON, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _inline(*buttons: tuple[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in buttons]
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return _inline((texts.BTN_CONFIRM, "f:ok"), (texts.BTN_EDIT, "f:edit"))


def watch_keyboard() -> InlineKeyboardMarkup:
    return _inline((texts.BTN_WATCH_YES, "w:yes"), (texts.BTN_WATCH_NO, "w:no"))


def feedback_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    return _inline(("👍", f"fb:{listing_id}:1"), ("👎", f"fb:{listing_id}:-1"))


def delete_keyboard() -> InlineKeyboardMarkup:
    return _inline((texts.BTN_DELETE_YES, "del:yes"), (texts.BTN_DELETE_NO, "del:no"))
