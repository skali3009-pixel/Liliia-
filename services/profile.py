"""Изменение профиля после анкеты.

Анкета заполняется один раз, а жизнь меняется: цель, режим активности,
питание, аллергии. Без возможности это поправить единственным выходом
остаётся удалить всё и начать заново — так продукты не делают.

Норма калорий зависит от пола, веса, роста, возраста, активности и цели.
Значит, при изменении любого из этих полей её нужно пересчитать, иначе
человек продолжит есть по старой цифре и не поймёт почему.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models import ActivityLevelEnum, DietTypeEnum, GoalEnum, User
from utils.formulas import ActivityLevel, Gender, Goal, calculate_macros, daily_water_ml

logger = logging.getLogger(__name__)

# Границы правдоподобия. Живут здесь, а не в обработчике: анкета и
# редактирование профиля должны проверять ввод одинаково, иначе через одну
# дверь пройдёт то, что не пустили в другую.
MIN_AGE, MAX_AGE = 10, 100
MIN_HEIGHT_CM, MAX_HEIGHT_CM = 100.0, 250.0
MIN_WEIGHT_KG, MAX_WEIGHT_KG = 30.0, 300.0
MIN_TARGET_KG, MAX_TARGET_KG = MIN_WEIGHT_KG, MAX_WEIGHT_KG

# Поля, которые человек может поменять сам, и то, влияют ли они на норму.
EDITABLE = {
    "goal": True,
    "activity": True,
    "age": True,
    "height": True,
    "diet": False,
    "allergies": False,
    "target_weight": False,
}


def can_recalculate(user: User) -> bool:
    """Хватает ли данных, чтобы пересчитать норму."""
    return all((user.gender, user.age, user.height_cm, user.current_weight_kg,
                user.activity_level, user.goal))


def recalculate(user: User) -> bool:
    """Пересчитать норму КБЖУ и воду под текущие поля профиля."""
    if not can_recalculate(user):
        return False

    macros = calculate_macros(
        gender=Gender(user.gender.value),
        weight_kg=user.current_weight_kg,
        height_cm=user.height_cm,
        age_years=user.age,
        activity_level=ActivityLevel(user.activity_level.value),
        goal=Goal(user.goal.value),
    )
    user.daily_calories = macros.calories
    user.daily_protein_g = macros.protein_g
    user.daily_fat_g = macros.fat_g
    user.daily_carbs_g = macros.carbs_g
    user.daily_fiber_g = macros.fiber_g
    user.daily_water_ml = daily_water_ml(
        weight_kg=user.current_weight_kg,
        activity_level=ActivityLevel(user.activity_level.value),
    )
    return True


async def set_goal(session: AsyncSession, user: User, value: str) -> bool:
    user.goal = GoalEnum(value)
    updated = recalculate(user)
    await session.commit()
    return updated


async def set_activity(session: AsyncSession, user: User, value: str) -> bool:
    user.activity_level = ActivityLevelEnum(value)
    updated = recalculate(user)
    await session.commit()
    return updated


async def set_age(session: AsyncSession, user: User, value: int) -> bool:
    user.age = value
    updated = recalculate(user)
    await session.commit()
    return updated


async def set_height(session: AsyncSession, user: User, value: float) -> bool:
    user.height_cm = value
    updated = recalculate(user)
    await session.commit()
    return updated


async def set_diet(session: AsyncSession, user: User, value: str) -> bool:
    """Тип питания на норму не влияет — только на подбор блюд."""
    user.diet_type = DietTypeEnum(value)
    await session.commit()
    return False


async def set_allergies(session: AsyncSession, user: User, text: str) -> None:
    """Пустая строка и «нет» означают одно: ограничений нет."""
    cleaned = (text or "").strip()
    user.allergies = None if cleaned.lower() in {"", "-", "нет", "никаких"} else cleaned[:200]
    await session.commit()


async def set_target_weight(session: AsyncSession, user: User, value: float) -> None:
    user.target_weight_kg = value
    await session.commit()


async def toggle_reminders(session: AsyncSession, user: User) -> bool:
    """Включить/выключить мягкие напоминания. Возвращает новое состояние."""
    user.reminders_enabled = not user.reminders_enabled
    await session.commit()
    return user.reminders_enabled


def valid_target(value: float | None) -> bool:
    return value is not None and MIN_TARGET_KG <= value <= MAX_TARGET_KG


def valid_age(value: int | None) -> bool:
    return value is not None and MIN_AGE <= value <= MAX_AGE


def valid_height(value: float | None) -> bool:
    return value is not None and MIN_HEIGHT_CM <= value <= MAX_HEIGHT_CM


__all__ = [
    "EDITABLE",
    "MAX_AGE",
    "MAX_HEIGHT_CM",
    "MAX_TARGET_KG",
    "MAX_WEIGHT_KG",
    "MIN_AGE",
    "MIN_HEIGHT_CM",
    "MIN_TARGET_KG",
    "MIN_WEIGHT_KG",
    "can_recalculate",
    "recalculate",
    "set_activity",
    "set_age",
    "set_allergies",
    "set_diet",
    "set_goal",
    "set_height",
    "set_target_weight",
    "toggle_reminders",
    "valid_age",
    "valid_height",
    "valid_target",
]
