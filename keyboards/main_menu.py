"""Главное reply-меню приложения (минимум текста, максимум кнопок/эмодзи)."""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# Первой кнопкой — «и что теперь?». Это единственный вопрос, с которым
# человек открывает бота, не зная, что нажать.
MENU_TURN = "🐆 Мой ход"
MENU_ADD_MEAL = "📷 Добавить еду"
MENU_WATER = "💧 Вода"
MENU_WORKOUT = "🏋️ Тренировка"
MENU_PROGRESS = "📊 Прогресс"
MENU_WHAT_TO_EAT = "🍽️ Что съесть"
MENU_PROFILE = "⚙️ Профиль"


# Все кнопки меню одним множеством. Нужно тем сценариям, которые ждут от
# человека текст: нажатая кнопка меню — это выход из сценария, а не ответ.
MENU_TEXTS = {MENU_TURN, MENU_ADD_MEAL, MENU_WATER, MENU_WORKOUT, MENU_PROGRESS,
              MENU_WHAT_TO_EAT, MENU_PROFILE}


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=MENU_TURN)
    builder.button(text=MENU_ADD_MEAL)
    builder.button(text=MENU_WATER)
    builder.button(text=MENU_WORKOUT)
    builder.button(text=MENU_PROGRESS)
    builder.button(text=MENU_WHAT_TO_EAT)
    builder.button(text=MENU_PROFILE)
    builder.adjust(1, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True)
