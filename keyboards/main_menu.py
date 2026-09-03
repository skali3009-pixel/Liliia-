"""Главное reply-меню приложения (минимум текста, максимум кнопок/эмодзи)."""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

MENU_ADD_MEAL = "📷 Добавить еду"
MENU_WATER = "💧 Вода"
MENU_WORKOUT = "🏋️ Тренировка"
MENU_PROGRESS = "📊 Прогресс"
MENU_WHAT_TO_EAT = "🍽️ Что съесть"
MENU_PROFILE = "⚙️ Профиль"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=MENU_ADD_MEAL)
    builder.button(text=MENU_WATER)
    builder.button(text=MENU_WORKOUT)
    builder.button(text=MENU_PROGRESS)
    builder.button(text=MENU_WHAT_TO_EAT)
    builder.button(text=MENU_PROFILE)
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)
