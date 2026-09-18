"""Кнопки под напоминанием о препарате."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from db import get_session
from models import User
from services.supplements import mark

logger = logging.getLogger(__name__)
router = Router(name="supplements")

CB_TAKE = "sup:take:"
CB_SKIP = "sup:skip:"


async def _mark(callback: CallbackQuery, *, skipped: bool) -> None:
    prefix = CB_SKIP if skipped else CB_TAKE
    supplement_id = int(callback.data.removeprefix(prefix))

    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None:
            await callback.answer("Сначала настрой профиль: /start", show_alert=True)
            return
        try:
            await mark(
                session,
                user_id=user.id,
                supplement_id=supplement_id,
                skipped=skipped,
                timezone_name=user.timezone,
            )
        except ValueError:
            await callback.answer("Препарат больше не в списке", show_alert=True)
            return

    mark_text = "⏭ Пропущено" if skipped else "✅ Принято"
    await callback.message.edit_text(f"{callback.message.text}\n\n{mark_text}")
    await callback.answer(mark_text)


@router.callback_query(F.data.startswith(CB_TAKE))
async def take(callback: CallbackQuery) -> None:
    await _mark(callback, skipped=False)


@router.callback_query(F.data.startswith(CB_SKIP))
async def skip(callback: CallbackQuery) -> None:
    await _mark(callback, skipped=True)
