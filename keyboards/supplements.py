"""Клавиатура напоминания о препарате."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.supplements import CB_SKIP, CB_TAKE


def reminder_keyboard(supplement_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принял", callback_data=f"{CB_TAKE}{supplement_id}")
    builder.button(text="⏭ Пропустить", callback_data=f"{CB_SKIP}{supplement_id}")
    builder.adjust(2)
    return builder.as_markup()
