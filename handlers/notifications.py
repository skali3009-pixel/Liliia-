"""Что происходит, когда человек нажимает кнопку под сообщением бота.

Три ответа, и каждый обязан быть настоящим. «+250 мл» действительно
записывает воду — не открывает экран, где это можно сделать. «Позже»
действительно убирает тему на несколько часов. «Сегодня не надо» —
до завтра.

Заодно здесь ставится отметка о том, чем закончилось сообщение. Без неё
не работает ни счёт усталости, ни ответ на вопрос, помогает ли вообще
хоть одно уведомление: отправленных много, полезных — неизвестно сколько.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery

from db import get_session
from keyboards.notifications import CB_LATER, CB_MUTE, CB_WATER
from models import User
from models.notification import (KINDS, RESULT_ACTED, RESULT_MUTED,
                                 RESULT_SNOOZED)
from services import notifications
from services.water import add_water, today_total_ml
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds

logger = logging.getLogger(__name__)
router = Router(name="notifications")


async def _clear_buttons(callback: CallbackQuery) -> None:
    """Кнопки исчезают после нажатия: нажатая дважды «Позже» сбивает с толку."""
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("Кнопки уже убраны")


@router.callback_query(F.data.startswith(CB_WATER))
async def add_from_nudge(callback: CallbackQuery) -> None:
    """Вода прямо из уведомления, без открытия приложения."""
    try:
        amount = int(callback.data[len(CB_WATER):])
    except ValueError:
        await callback.answer()
        return

    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None:
            await callback.answer()
            return
        tz = user.timezone or DEFAULT_TIMEZONE
        await add_water(session, user_id=user.id, amount_ml=amount)
        total = await today_total_ml(session, user.id, timezone_name=tz)
        norm = user.daily_water_ml
        await notifications.mark(session, user.id, "water", RESULT_ACTED)

    line = f"💧 Записала {amount} мл. Сегодня {round(total)} мл"
    if norm:
        line += f" из {norm}"
    await _clear_buttons(callback)
    await callback.message.answer(line)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_LATER))
async def later(callback: CallbackQuery) -> None:
    kind = callback.data[len(CB_LATER):]
    if kind not in KINDS:
        await callback.answer()
        return

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        await notifications.snooze(
            session, callback.from_user.id, kind,
            until=now + timedelta(hours=notifications.SNOOZE_HOURS),
        )
        await notifications.mark(session, callback.from_user.id, kind, RESULT_SNOOZED)

    await _clear_buttons(callback)
    await callback.answer("Хорошо, вернусь к этому позже", show_alert=False)


@router.callback_query(F.data.startswith(CB_MUTE))
async def not_today(callback: CallbackQuery) -> None:
    kind = callback.data[len(CB_MUTE):]
    if kind not in KINDS:
        await callback.answer()
        return

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        tz = (user.timezone if user else None) or DEFAULT_TIMEZONE
        # Молчим до конца именно её суток, а не «плюс сутки от сейчас»:
        # нажатое в одиннадцать вечера «сегодня не надо» не должно съедать
        # весь следующий день.
        _, end_of_day = day_bounds(tz, now=now)
        await notifications.snooze(session, callback.from_user.id, kind,
                                   until=end_of_day)
        await notifications.mark(session, callback.from_user.id, kind, RESULT_MUTED)

    await _clear_buttons(callback)
    await callback.answer("Сегодня об этом больше не напомню")


__all__ = ["router"]
