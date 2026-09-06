"""Кнопка «Мой ход» в чате: реакция гепарда и одно действие.

Весь ум приложения — подсказка «что сделать сейчас» и гепард, который на
день отзывается, — жил только в мини-приложении. Человеку, который ведёт
дневник перепиской, не доставалось ничего: бот молча записывал еду.

Считается всё тем же кодом, что и в приложении (services/turn.py), поэтому
в чате и на экране человек видит одно и то же, а не два разных мнения.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import get_session
from keyboards.main_menu import MENU_TURN, main_menu_keyboard
from models import User
from services import turn as turn_service

logger = logging.getLogger(__name__)
router = Router(name="turn")


def _app_button(action) -> InlineKeyboardMarkup | None:
    """Кнопка в приложение — только для того, чего в чате не сделать.

    Отметить самочувствие или заготовку можно лишь на экране. Называть в
    таком случае кнопку нижнего меню было бы враньём.
    """
    if action is None or not config.WEBAPP_URL:
        return None
    if turn_service.chat_hint(action) is not None:
        return None

    builder = InlineKeyboardBuilder()
    builder.button(text=action.cta, web_app=WebAppInfo(url=config.WEBAPP_URL))
    return builder.as_markup()


@router.message(F.text == MENU_TURN)
async def show_turn(message: Message, state: FSMContext) -> None:
    # Кнопка меню важнее недописанного ответа: иначе «Мой ход», нажатый
    # посреди добавления еды, уедет в распознавание как название блюда.
    await state.clear()

    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None or not user.onboarding_completed:
            await message.answer("Сначала настроим профиль — напиши /start.")
            return
        turn = await turn_service.build(session, user)

    keyboard = _app_button(turn.action)
    await message.answer(turn_service.render(turn),
                         reply_markup=keyboard or main_menu_keyboard())
