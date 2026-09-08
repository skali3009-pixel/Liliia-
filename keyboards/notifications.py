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
    "today": "today",
    "water": "today",
    "meal": "today",
    "cube": "cube",
    "workout": "gym",
    "steps": "today",
    "checkin": "today",
    "progress": "progress",
}


def deep_link(target: str) -> str | None:
    """Адрес приложения, открытого сразу на нужной вкладке.

    None — если вести некуда. Пустая цель бывает намеренно: у вечернего
    «на сегодня достаточно» кнопки действия нет и быть не должно.
    """
    screen = SCREEN.get(target)
    if not config.WEBAPP_URL or not screen:
        return None
    base = config.WEBAPP_URL.rstrip("/")
    return f"{base}?{urlencode({'screen': screen})}"


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


def comeback_keyboard() -> InlineKeyboardMarkup | None:
    """Кнопка под письмом тому, кто пропал.

    Одна и без вариантов: «позже» и «сегодня не надо» здесь не нужны —
    таких писем всего два за всё отсутствие, и оба заканчиваются словами
    о том, как их выключить. Кнопка ведёт на «Сегодня», а не в список
    накопившихся целей: после долгого перерыва человеку нужен один
    маленький шаг, а не отчёт о том, сколько он пропустил.
    """
    link = deep_link("today")
    if link is None:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text="Продолжить", web_app=WebAppInfo(url=link))
    return builder.as_markup()


__all__ = ["CB_LATER", "CB_MUTE", "CB_WATER", "SCREEN", "comeback_keyboard",
           "deep_link", "nudge_keyboard"]
