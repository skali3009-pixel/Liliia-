"""Клавиатура трекера воды."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.water import BOTTLE_ML, GLASS_ML, MUG_ML

CB_PREFIX = "water:"
CB_UNDO = "water:undo"


def water_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🥛 Стакан {GLASS_ML}", callback_data=f"{CB_PREFIX}{GLASS_ML}")
    builder.button(text=f"☕ Кружка {MUG_ML}", callback_data=f"{CB_PREFIX}{MUG_ML}")
    builder.button(text=f"🍶 Бутылка {BOTTLE_ML}", callback_data=f"{CB_PREFIX}{BOTTLE_ML}")
    builder.button(text="↩️ Убрать последнее", callback_data=CB_UNDO)
    builder.adjust(3, 1)
    return builder.as_markup()
