"""Главное reply-меню приложения (минимум текста, максимум кнопок/эмодзи)."""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# Первой кнопкой — «и что теперь?». Это единственный вопрос, с которым
# человек открывает бота, не зная, что нажать.
MENU_TURN = "🐆 Мой ход"
MENU_ADD_MEAL = "📷 Добавить еду"
MENU_WATER = "💧 Вода"
MENU_STEPS = "👟 Шаги"
MENU_WORKOUT = "🏋️ Тренировка"
MENU_PROGRESS = "📊 Прогресс"
MENU_WHAT_TO_EAT = "🍽️ Что съесть"
MENU_PROFILE = "⚙️ Профиль"
# Второй проект Лилии. Карточка приходит один раз, в конце анкеты, и без
# пути назад «один раз» означает «больше никогда»: команда `/music` такой
# путь даёт, но её не видно — в синем списке команд её нет (список держится
# на десяти строках). Кнопка в меню и есть видимый вход.
MENU_MUSIC = "🎧 Музыка SCALIA"


# Все кнопки меню одним множеством. Нужно тем сценариям, которые ждут от
# человека текст: нажатая кнопка меню — это выход из сценария, а не ответ.
#
# Забыть здесь новую кнопку — тихая ошибка: человек, начавший вводить шаги
# или правку роста, нажмёт её, и сценарий съест нажатие как ответ. Стоит
# тест, что множество и клавиатура описывают одни и те же кнопки.
MENU_TEXTS = {MENU_TURN, MENU_ADD_MEAL, MENU_WATER, MENU_STEPS, MENU_WORKOUT,
              MENU_PROGRESS, MENU_WHAT_TO_EAT, MENU_PROFILE, MENU_MUSIC}


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=MENU_TURN)
    builder.button(text=MENU_ADD_MEAL)
    builder.button(text=MENU_WATER)
    builder.button(text=MENU_STEPS)
    builder.button(text=MENU_WORKOUT)
    builder.button(text=MENU_PROGRESS)
    builder.button(text=MENU_WHAT_TO_EAT)
    builder.button(text=MENU_PROFILE)
    builder.button(text=MENU_MUSIC)
    # «Мой ход» во всю ширину сверху, дальше парами. Шаги вносят
    # каждый день, поэтому кнопка нужна на виду, а не в приложении.
    #
    # Музыка — своей строкой внизу, а не в пару к «Профилю». Подходящего
    # места в готовых строках нет: наверху главное действие, дальше пары
    # ежедневных дел, и музыка ни с одним из них не рифмуется. А поставить
    # её рядом с «Профилем» значило бы сузить его вдвое — кнопку, которую
    # никто не просил трогать. Лишняя строка стоит высоты клавиатуры, и это
    # честная цена: остальные кнопки остались ровно там, где были.
    builder.adjust(1, 2, 2, 2, 1, 1)
    return builder.as_markup(resize_keyboard=True)
