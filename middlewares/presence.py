"""Отметка о том, что человек прямо сейчас разговаривает с ботом.

Здесь же считаются нажатия кнопок меню: обе отметки ставятся на одно и то
же событие, и разносить их по двум мидлварам значило бы дважды пройти
один и тот же путь ради одной записи.

Нужна ровно для одного: не писать первым тому, кто и так здесь. Подсказка
«запиши еду», прилетевшая через минуту после того, как человек эту еду
записал, — самый быстрый способ научить его выключать уведомления.

Пишем не на каждое нажатие. Точность до минуты здесь не нужна, а запись в
базу на каждое сообщение — это лишняя запись на каждое сообщение.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import config
from db import get_session
from keyboards.main_menu import MENU_TEXTS
from models import User
from services import buttons

logger = logging.getLogger(__name__)

# Чаще этого отметку не обновляем.
GRANULARITY = timedelta(minutes=5)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class PresenceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            try:
                await self._touch(event.from_user.id)
            except Exception:
                # Отметка присутствия не стоит того, чтобы из-за неё
                # человеку не ответили.
                logger.debug("Не удалось отметить присутствие", exc_info=True)

        text = getattr(event, "text", None)
        if config.BUTTON_STATS and text in MENU_TEXTS and event.from_user:
            try:
                await self._count(event.from_user.id, text)
            except Exception:
                logger.debug("Не удалось записать нажатие", exc_info=True)

        return await handler(event, data)

    @staticmethod
    async def _count(user_id: int, text: str) -> None:
        async with get_session() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            await buttons.note(session, user_id, text,
                               timezone_name=user.timezone or "Europe/Moscow")

    @staticmethod
    async def _touch(user_id: int) -> None:
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            last = user.last_bot_action
            if last is not None and now - _aware(last) < GRANULARITY:
                return
            user.last_bot_action = now
            await session.commit()


__all__ = ["GRANULARITY", "PresenceMiddleware"]
