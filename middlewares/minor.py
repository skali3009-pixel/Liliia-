"""Профиль младше 18: персональных расчётов и советов нет, свои данные — есть.

Стоит после проверки оплаты и пропускает только то, что нужно человеку для
своих данных и поддержки: документы, выгрузку, удаление, «что-то не так»,
профиль (возраст мог быть указан с ошибкой) и ответы внутри этих сценариев.
Всё остальное — одна и та же спокойная строка вместо норм и подбора.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from db import get_session
from keyboards.main_menu import MENU_DOCS, MENU_PROFILE
from models import User
from services import age as age_rules

OPEN_COMMANDS = {"/legal", "/delete", "/stop_ads", "/export", "/problem", "/help"}
# Кнопки под сообщениями: документы и удаление, профиль, выгрузка, жалоба.
OPEN_CALLBACKS = ("legal:", "prof_", "feedback", "fb_")
# Сценарии, внутри которых человек отвечает текстом: правка профиля и жалоба.
OPEN_STATES = ("ProfileStates:", "FeedbackStates:")


def _is_open(event: TelegramObject, raw_state: str | None) -> bool:
    if raw_state and raw_state.startswith(OPEN_STATES):
        return True
    if isinstance(event, Message):
        text = (event.text or "").strip()
        if text in (MENU_PROFILE, MENU_DOCS):
            return True
        return bool(text.startswith("/") and
                    text.split()[0].split("@")[0] in OPEN_COMMANDS)
    if isinstance(event, CallbackQuery):
        return (event.data or "").startswith(OPEN_CALLBACKS)
    return False


class MinorMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        who = data.get("event_from_user")
        if who is None or _is_open(event, data.get("raw_state")):
            return await handler(event, data)

        async with get_session() as session:
            user = await session.get(User, who.id)
        # До конца анкеты возраст решает сама анкета — там свой отказ.
        if user is None or not user.onboarding_completed or not age_rules.is_minor(user):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(age_rules.NOTICE)
        elif isinstance(event, Message):
            await event.answer(age_rules.NOTICE)
        return None
