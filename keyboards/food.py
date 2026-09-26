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
# После сохранения: номер записи в данных кнопки, а не в состоянии разговора.
# Кнопка живёт в переписке дольше любого состояния, и через час «Отменить»
# обязано убрать ровно ту запись, под которой стоит.
CB_UNDO = "food:undo:"
CB_FIX = "food:fix:"


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


def saved_keyboard(meal_id: int) -> InlineKeyboardMarkup:
    """«Отменить» и «Исправить» под итогом только что сделанной записи.

    Ошибку замечают ровно здесь — глядя на итог дня. Отправлять человека
    искать запись в /day значит, что ошибка чаще останется в дневнике.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="⚖️ Исправить вес", callback_data=f"{CB_FIX}{meal_id}")
    builder.button(text="↩️ Отменить запись", callback_data=f"{CB_UNDO}{meal_id}")
    builder.adjust(2)
    return builder.as_markup()
