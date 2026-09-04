"""Кнопка «Прогресс» в чате: краткая сводка и переход в приложение."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import get_session
from keyboards.main_menu import MENU_PROGRESS
from models import User
from services.meals import get_today_totals
from services.progress import compute_streak, meal_days, measure_points
from utils.timeframe import today_in

logger = logging.getLogger(__name__)
router = Router(name="progress")


def _open_app_keyboard() -> InlineKeyboardMarkup | None:
    if not config.WEBAPP_URL:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📈 Открыть прогресс", web_app=WebAppInfo(url=config.WEBAPP_URL)
    )
    return builder.as_markup()


@router.message(F.text == MENU_PROGRESS)
async def show_progress(message: Message) -> None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None or not user.onboarding_completed:
            await message.answer("Сначала настроим профиль — напиши /start.")
            return

        tz = user.timezone
        weights = await measure_points(session, user.id, field="weight", days=3650,
                                       timezone_name=tz)
        streak = compute_streak(await meal_days(session, user.id, timezone_name=tz),
                                today=today_in(tz))
        totals = await get_today_totals(session, user.id, timezone_name=tz)
        norm = user.daily_calories

    lines = ["📊 Твой прогресс", ""]

    current = weights[-1].value if weights else user.current_weight_kg
    if current:
        lines.append(f"⚖️ Сейчас: {current:.1f} кг")
        if len(weights) > 1:
            change = current - weights[0].value
            sign = "−" if change < 0 else "+"
            lines.append(f"   {sign}{abs(change):.1f} кг за всё время")
        if user.target_weight_kg:
            left = current - user.target_weight_kg
            lines.append(
                f"   до цели {user.target_weight_kg:.1f} кг осталось {abs(left):.1f} кг"
                if abs(left) > 0.1 else "   цель достигнута 🎉"
            )
    else:
        lines.append("⚖️ Вес ещё не записан — добавь замер в приложении")

    lines += ["", f"🔥 Сегодня: {round(totals.calories)} из {norm or '—'} ккал"]
    if streak:
        lines.append(f"📅 Записываешь еду {streak} дней подряд")

    keyboard = _open_app_keyboard()
    if keyboard is None:
        lines += ["", "Графики и замеры — в приложении (кнопка «Дневник» у поля ввода)."]

    await message.answer("\n".join(lines), reply_markup=keyboard)
