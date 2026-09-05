"""Кнопка «Тренировка» в чате: сводка за неделю и переход в приложение."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import get_session
from keyboards.main_menu import MENU_WORKOUT
from models import User
from services.workouts import week_summary

logger = logging.getLogger(__name__)
router = Router(name="workouts")


def _open_app_keyboard() -> InlineKeyboardMarkup | None:
    if not config.WEBAPP_URL:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text="🏋️ Открыть тренировки", web_app=WebAppInfo(url=config.WEBAPP_URL))
    return builder.as_markup()


@router.message(F.text == MENU_WORKOUT)
async def show_workouts(message: Message) -> None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None or not user.onboarding_completed:
            await message.answer("Сначала настроим профиль — напиши /start.")
            return
        week = await week_summary(session, user.id, timezone_name=user.timezone)

    lines = ["🏋️ Тренировки", ""]
    if week["workouts"]:
        lines += [
            f"За неделю: {week['workouts']} тренировок, {week['minutes']} мин, "
            f"{week['calories']} ккал",
            "",
        ]
    else:
        lines += ["За эту неделю тренировок пока не было.", ""]

    lines.append(
        "В приложении: программы для дома и зала, таймер отдыха между подходами, "
        "разбор техники по каждому упражнению и кардио с расчётом расхода."
    )

    keyboard = _open_app_keyboard()
    if keyboard is None:
        lines += ["", f"Открой приложение кнопкой «{config.WEBAPP_BUTTON}» у поля ввода."]

    await message.answer("\n".join(lines), reply_markup=keyboard)
