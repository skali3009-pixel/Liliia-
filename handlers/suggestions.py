"""Кнопка «Что съесть» в чате: остаток нормы и подбор блюд."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db import get_session
from keyboards.main_menu import MENU_WHAT_TO_EAT
from models import MealSourceEnum, User
from services.food_vision import FoodAnalysis, FoodRecognitionError
from services.meals import get_today_totals, save_meal
from services.suggestions import Suggestion, suggest_meals
from utils.macros import GAP_LABELS, dominant_gap, remaining
from utils.meal_time import MEAL_TYPE_RU, guess_meal_type
from utils.timeframe import get_zone

from datetime import datetime

logger = logging.getLogger(__name__)
router = Router(name="suggestions")

CB_EAT = "eat:"

# Варианты живут до перезапуска бота: класть их в базу ради одной кнопки ни к чему.
_offered: dict[str, Suggestion] = {}


def _keyboard(key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Съела это", callback_data=f"{CB_EAT}{key}")
    return builder.as_markup()


@router.message(F.text == MENU_WHAT_TO_EAT)
async def what_to_eat(message: Message) -> None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None or not user.onboarding_completed:
            await message.answer("Сначала настроим профиль — напиши /start.")
            return

        totals = await get_today_totals(session, user.id, timezone_name=user.timezone)
        norms = {
            "calories": user.daily_calories or 0,
            "protein_g": user.daily_protein_g or 0,
            "fat_g": user.daily_fat_g or 0,
            "carbs_g": user.daily_carbs_g or 0,
        }

    left = remaining(
        {"calories": totals.calories, "protein_g": totals.protein_g,
         "fat_g": totals.fat_g, "carbs_g": totals.carbs_g},
        norms,
    )
    gap = dominant_gap(left, norms)

    header = [
        f"🍽 Осталось на сегодня: {left.calories} ккал",
        f"Б {left.protein_g} · Ж {left.fat_g} · У {left.carbs_g} г",
    ]
    if gap:
        header.append(f"Сильнее всего не хватает {GAP_LABELS[gap]}.")
    if left.all_done:
        header.append("Норма на сегодня уже выбрана — лучше остановиться.")

    status = await message.answer("\n".join(header) + "\n\n🔍 Подбираю варианты…")

    try:
        async with get_session() as session:
            user = await session.get(User, message.from_user.id)
            suggestions = await suggest_meals(user, left, norms)
    except FoodRecognitionError as e:
        await status.edit_text("\n".join(header) + f"\n\n{e}")
        return
    except Exception:
        logger.exception("Ошибка подбора блюд")
        await status.edit_text("\n".join(header) + "\n\nНе получилось подобрать. Попробуй ещё раз.")
        return

    await status.edit_text("\n".join(header))

    for index, item in enumerate(suggestions):
        key = f"{message.from_user.id}:{index}"
        _offered[key] = item
        await message.answer(
            f"🍽 {item.name}\n"
            f"{round(item.weight_g)} г · {round(item.calories)} ккал\n"
            f"Б {round(item.protein_g)} · Ж {round(item.fat_g)} · У {round(item.carbs_g)} г\n\n"
            f"💬 {item.why}",
            reply_markup=_keyboard(key),
        )


@router.callback_query(F.data.startswith(CB_EAT))
async def eat_suggestion(callback: CallbackQuery) -> None:
    key = callback.data.removeprefix(CB_EAT)
    item = _offered.get(key)
    if item is None:
        await callback.answer("Вариант устарел — запроси подбор заново", show_alert=True)
        return

    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None:
            await callback.answer("Сначала настрой профиль: /start", show_alert=True)
            return

        await save_meal(
            session,
            user_id=user.id,
            analysis=FoodAnalysis(
                name=item.name, weight_g=item.weight_g, calories=item.calories,
                protein_g=item.protein_g, fat_g=item.fat_g, carbs_g=item.carbs_g,
                confidence="medium", comment="",
            ),
            source=MealSourceEnum.TEXT,
            meal_type=guess_meal_type(datetime.now(get_zone(user.timezone))),
        )
        totals = await get_today_totals(session, user.id, timezone_name=user.timezone)

    _offered.pop(key, None)
    await callback.message.edit_text(
        f"{callback.message.text}\n\n✅ Записала. Сегодня: {round(totals.calories)} ккал"
    )
    await callback.answer("Записала")
