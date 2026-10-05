"""Recognize old device keyboards before router and FSM filters run."""

from aiogram import BaseMiddleware
from aiogram.types import Message

from keyboards.main_menu import LEGACY_MENU, main_menu_keyboard


class MenuAliasesMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text in LEGACY_MENU:
            normalized = event.model_copy(update={"text": LEGACY_MENU[event.text]})
            await event.answer("Меню обновлено — продолжаем.", reply_markup=main_menu_keyboard())
            return await handler(normalized, data)
        return await handler(event, data)
