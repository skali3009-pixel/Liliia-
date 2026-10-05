"""Главное reply-меню приложения (минимум текста, максимум кнопок/эмодзи)."""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# Первой кнопкой — «и что теперь?». Это единственный вопрос, с которым
# человек открывает бота, не зная, что нажать.
MENU_TURN = "🐆 Мой ход"
MENU_ADD_MEAL = "📷 Записать еду"
MENU_WATER = "💧 Вода"
MENU_STEPS = "👟 Шаги"
MENU_WORKOUT = "🏋️ Тренировка"
MENU_PROGRESS = "📊 День и прогресс"
MENU_WHAT_TO_EAT = "🍽️ Что съесть"
MENU_PROFILE = "⚙️ Профиль и доступ"
# Музыка доступна в профиле, через /music и старую клавиатуру.
MENU_MUSIC = "🎧 Музыка SCALIA"
# Документы показываются один раз, при согласии, и дальше жили только за
# командой `/legal` в синем списке — туда не смотрит никто. Лилия так и
# сказала: «появляются один раз в начале, и всё, потом их не посмотреть».
MENU_DOCS = "📄 Документы"

# Old reply keyboards stay on devices until Telegram receives a new one.
LEGACY_MENU = {
    "📷 Добавить еду": MENU_ADD_MEAL,
    "📊 Прогресс": MENU_PROGRESS,
    "⚙️ Профиль": MENU_PROFILE,
}


# Все кнопки меню одним множеством. Нужно тем сценариям, которые ждут от
# человека текст: нажатая кнопка меню — это выход из сценария, а не ответ.
#
# Забыть здесь новую кнопку — тихая ошибка: человек, начавший вводить шаги
# или правку роста, нажмёт её, и сценарий съест нажатие как ответ. Стоит
# тест, что множество и клавиатура описывают одни и те же кнопки.
MENU_TEXTS = {MENU_TURN, MENU_ADD_MEAL, MENU_WATER, MENU_STEPS, MENU_WORKOUT,
              MENU_PROGRESS, MENU_WHAT_TO_EAT, MENU_PROFILE, MENU_MUSIC, MENU_DOCS,
              *LEGACY_MENU}


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
    builder.button(text=MENU_DOCS)
    # «Мой ход» во всю ширину сверху, дальше парами. Шаги вносят
    # каждый день, поэтому кнопка нужна на виду, а не в приложении.
    #
    # Документы и профиль в последней паре; старые подписи принимает middleware.
    builder.adjust(1, 2, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True)
