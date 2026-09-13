"""Трекер воды: кнопка меню и быстрые добавления."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from db import get_session
from keyboards.main_menu import MENU_WATER
from keyboards.water import CB_PREFIX, CB_UNDO, water_keyboard
from models import User
from services.water import add_water, today_total_ml, undo_last
from utils.progress import format_remaining, render_progress_bar

logger = logging.getLogger(__name__)
router = Router(name="water")


def _render(total_ml: int, norm_ml: int | None) -> str:
    lines = [f"💧 Вода за сегодня: {total_ml} мл"]
    if norm_ml:
        lines += [
            f"{render_progress_bar(total_ml, norm_ml)} · "
            f"{format_remaining(total_ml, norm_ml)} мл до нормы"
        ]
    lines += ["", "Отмечай кнопками ниже 👇"]
    return "\n".join(lines)


async def _show(message: Message, user_id: int, *, edit: bool = False) -> None:
    async with get_session() as session:
        user = await session.get(User, user_id)
        if user is None or not user.onboarding_completed:
            await message.answer("Сначала настроим профиль — напиши /start.")
            return
        total = await today_total_ml(session, user_id, timezone_name=user.timezone)
        norm = user.daily_water_ml

    text = _render(total, norm)
    if edit:
        try:
            await message.edit_text(text, reply_markup=water_keyboard())
            return
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
            return
    await message.answer(text, reply_markup=water_keyboard())


@router.message(F.text == MENU_WATER)
async def show_water(message: Message) -> None:
    await _show(message, message.from_user.id)


@router.callback_query(F.data.startswith(CB_PREFIX) & ~F.data.endswith("undo"))
async def add_portion(callback: CallbackQuery) -> None:
    amount = int(callback.data.removeprefix(CB_PREFIX))

    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None:
            await callback.answer("Сначала настрой профиль: /start", show_alert=True)
            return
        await add_water(session, user_id=user.id, amount_ml=amount)

    await _show(callback.message, callback.from_user.id, edit=True)
    await callback.answer(f"+{amount} мл")


@router.callback_query(F.data == CB_UNDO)
async def undo_portion(callback: CallbackQuery) -> None:
    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None:
            await callback.answer("Сначала настрой профиль: /start", show_alert=True)
            return
        removed = await undo_last(session, user.id, timezone_name=user.timezone)

    await _show(callback.message, callback.from_user.id, edit=True)
    await callback.answer(f"−{removed} мл" if removed else "Сегодня ещё нечего убирать")
