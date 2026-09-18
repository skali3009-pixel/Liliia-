"""Проверка доступа: без активной подписки бот отвечает только про оплату.

Пропускаем то, без чего человек не сможет ни начать, ни заплатить: команду
/start, экран подписки, сами платежи и админские команды. Всё остальное
упирается в предложение оформить доступ.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import config
from db import get_session
from handlers.access import CB_BUY, buy_keyboard, paywall_text
from services.subscriptions import check_access

logger = logging.getLogger(__name__)

# Команды, которые работают всегда — иначе из закрытого бота не выбраться.
OPEN_COMMANDS = {
    "/start", "/subscription", "/admin", "/grant", "/help",
    # Документы, отзыв согласия и отказ от рекламы должны работать всегда:
    # закон не спрашивает, оплачена ли подписка.
    "/legal", "/delete", "/stop_ads",
}


def _is_open(event: TelegramObject) -> bool:
    """Пускать ли это событие мимо проверки доступа."""
    if isinstance(event, Message):
        # Оплата и её подтверждение обязаны проходить в любом состоянии.
        if event.successful_payment is not None:
            return True
        text = (event.text or "").strip()
        return text.split()[0].split("@")[0] in OPEN_COMMANDS if text.startswith("/") else False

    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return data.startswith(CB_BUY) or data.startswith("legal:")

    return False


class AccessMiddleware(BaseMiddleware):
    """Отсекает всё, что делается без оплаченного доступа."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not config.PAYWALL or _is_open(event):
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        async with get_session() as session:
            access = await check_access(session, user.id)

        if access.allowed:
            return await handler(event, data)

        # Дальше обработчик не зовём: показываем, как вернуть доступ.
        if isinstance(event, CallbackQuery):
            await event.answer("Доступ закрыт — оформи подписку", show_alert=True)
            await event.message.answer(paywall_text(access), reply_markup=buy_keyboard())
        elif isinstance(event, Message):
            await event.answer(paywall_text(access), reply_markup=buy_keyboard())
        return None
