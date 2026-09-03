"""Клавиатура карточки распознанного блюда."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

CB_SAVE = "food:save"
CB_CANCEL = "food:cancel"
CB_LESS = "food:less"
CB_MORE = "food:more"
CB_WEIGHT = "food:weight"
CB_WRONG_DISH = "food:wrong"


def food_card_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➖ Меньше", callback_data=CB_LESS)
    builder.button(text="➕ Больше", callback_data=CB_MORE)
    builder.button(text="⚖️ Указать вес", callback_data=CB_WEIGHT)
    builder.button(text="🔄 Не то блюдо", callback_data=CB_WRONG_DISH)
    builder.button(text="✅ Сохранить", callback_data=CB_SAVE)
    builder.button(text="❌ Отмена", callback_data=CB_CANCEL)
    builder.adjust(2, 2, 2)
    return builder.as_markup()
