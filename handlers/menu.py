"""Обработчики кнопок главного меню.

Реализован раздел «Профиль» (данные анкеты + рассчитанная норма). Остальные
разделы (фото еды, вода, тренировки, прогресс, рекомендации по рациону) —
следующие этапы, пока отвечают заглушкой, чтобы кнопки не оставались без
ответа.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from db import get_session
from keyboards.main_menu import (
    MENU_ADD_MEAL,
    MENU_PROGRESS,
    MENU_WATER,
    MENU_WHAT_TO_EAT,
    MENU_WORKOUT,
)
from models import User

router = Router(name="main_menu")

_STUB_TEXT: dict[str, str] = {
    MENU_ADD_MEAL: "Распознавание еды по фото — в разработке 🚧",
    MENU_WATER: "Трекер воды — в разработке 🚧",
    MENU_WORKOUT: "Тренировки — в разработке 🚧",
    MENU_PROGRESS: "Аналитика прогресса — в разработке 🚧",
    MENU_WHAT_TO_EAT: "Рекомендации по рациону — в разработке 🚧",
}

GENDER_RU = {"male": "мужской", "female": "женский"}
ACTIVITY_RU = {
    "sedentary": "сидячий образ жизни",
    "light": "лёгкая",
    "moderate": "умеренная",
    "high": "высокая",
    "very_high": "очень высокая",
}
GOAL_RU = {
    "lose_weight": "похудение",
    "maintain": "поддержание",
    "gain_mass": "набор массы",
    "recomposition": "рельеф",
}
DIET_RU = {
    "regular": "обычное",
    "vegan": "веган",
    "vegetarian": "вегетарианское",
    "gluten_free": "без глютена",
}


@router.message(F.text.in_(_STUB_TEXT))
async def handle_stub(message: Message) -> None:
    await message.answer(_STUB_TEXT[message.text])


@router.message(F.text == "⚙️ Профиль")
async def handle_profile(message: Message) -> None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)

    if user is None or not user.onboarding_completed:
        await message.answer("Профиль ещё не настроен. Напиши /start.")
        return

    await message.answer(
        "⚙️ Твой профиль:\n\n"
        f"Пол: {GENDER_RU.get(user.gender.value, user.gender.value)}\n"
        f"Возраст: {user.age}\n"
        f"Рост: {user.height_cm:.0f} см\n"
        f"Вес: {user.current_weight_kg:.1f} кг → цель {user.target_weight_kg:.1f} кг\n"
        f"Активность: {ACTIVITY_RU.get(user.activity_level.value, user.activity_level.value)}\n"
        f"Цель: {GOAL_RU.get(user.goal.value, user.goal.value)}\n"
        f"Питание: {DIET_RU.get(user.diet_type.value, user.diet_type.value)}\n"
        f"Аллергии: {user.allergies or 'нет'}\n\n"
        f"🔥 Норма: {user.daily_calories} ккал | "
        f"Б {user.daily_protein_g} / Ж {user.daily_fat_g} / У {user.daily_carbs_g} г\n"
        f"💧 Вода: {user.daily_water_ml} мл"
    )
