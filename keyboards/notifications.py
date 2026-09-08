"""Кнопки под сообщением, которое бот написал первым.

Три штуки, и больше не бывает. Первая — само действие; вторая и третья
существуют, чтобы человек мог остановить разговор, не выключая бота
целиком. Кнопка «Позже», которая ничего не меняет, хуже её отсутствия:
она учит, что бота слушать бесполезно.

Действие по возможности делается прямо здесь, в чате: вода добавляется
одним нажатием. Там, где нужен экран, кнопка открывает не «приложение
вообще», а ту вкладку, где действие выполняется.
"""

from __future__ import annotations

from urllib.parse import urlencode

from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config

CB_WATER = "nudge:water:"     # + миллилитры
CB_LATER = "nudge:later:"     # + категория
CB_MUTE = "nudge:mute:"       # + категория

# Куда ведёт совет. Открывать главный экран в ответ на «подобрать еду» —
# значит заставить человека искать нужную вкладку самому.
SCREEN = {
    "water": "today",
    "meal": "today",
    "cube": "cube",
    "workout": "gym",
    "steps": "today",
    "checkin": "today",
    "progress": "progress",
}


def deep_link(target: str) -> str | None:
    """Адрес приложения, открытого сразу на нужной вкладке."""
    if not config.WEBAPP_URL:
        return None
    screen = SCREEN.get(target)
    base = config.WEBAPP_URL.rstrip("/")
    return f"{base}?{urlencode({'screen': screen})}" if screen else base


def nudge_keyboard(*, target: str, cta: str, kind: str,
                   amount: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if target == "water" and amount:
        # Единственное действие, которое целиком делается в чате.
        builder.button(text=f"+{amount} мл", callback_data=f"{CB_WATER}{amount}")
    else:
        link = deep_link(target)
        if link:
            builder.button(text=cta, web_app=WebAppInfo(url=link))

    builder.button(text="Позже", callback_data=f"{CB_LATER}{kind}")
    builder.button(text="Сегодня не надо", callback_data=f"{CB_MUTE}{kind}")
    builder.adjust(1, 2)
    return builder.as_markup()


__all__ = ["CB_LATER", "CB_MUTE", "CB_WATER", "SCREEN", "deep_link",
           "nudge_keyboard"]
