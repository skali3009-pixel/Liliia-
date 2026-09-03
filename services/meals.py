"""Работа с приёмами пищи в БД: сохранение и дневные итоги."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Meal, MealSourceEnum, MealTypeEnum
from services.food_vision import FoodAnalysis


@dataclass(frozen=True)
class DayTotals:
    """Сколько уже съедено за сегодня."""

    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float


def _day_start_utc(now: datetime | None = None) -> datetime:
    """Начало текущих суток в UTC.

    MVP: сутки считаются по UTC. Персональные часовые пояса — отдельная
    задача (нужно поле timezone в users и запрос его в онбординге).
    """
    moment = now or datetime.now(timezone.utc)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


async def save_meal(
    session: AsyncSession,
    *,
    user_id: int,
    analysis: FoodAnalysis,
    source: MealSourceEnum,
    meal_type: MealTypeEnum,
    photo_file_id: str | None = None,
) -> Meal:
    """Сохранить распознанный приём пищи."""
    meal = Meal(
        user_id=user_id,
        meal_type=meal_type,
        name=analysis.name,
        weight_g=analysis.weight_g,
        calories=analysis.calories,
        protein_g=analysis.protein_g,
        fat_g=analysis.fat_g,
        carbs_g=analysis.carbs_g,
        source=source,
        photo_file_id=photo_file_id,
    )
    session.add(meal)
    await session.commit()
    return meal


async def get_today_totals(session: AsyncSession, user_id: int) -> DayTotals:
    """Суммарные КБЖУ за сегодня."""
    stmt = select(
        func.coalesce(func.sum(Meal.calories), 0.0),
        func.coalesce(func.sum(Meal.protein_g), 0.0),
        func.coalesce(func.sum(Meal.fat_g), 0.0),
        func.coalesce(func.sum(Meal.carbs_g), 0.0),
    ).where(Meal.user_id == user_id, Meal.logged_at >= _day_start_utc())

    calories, protein_g, fat_g, carbs_g = (await session.execute(stmt)).one()
    return DayTotals(
        calories=float(calories),
        protein_g=float(protein_g),
        fat_g=float(fat_g),
        carbs_g=float(carbs_g),
    )


async def delete_meal(session: AsyncSession, meal: Meal) -> None:
    """Удалить запись (кнопка «Отменить» сразу после сохранения)."""
    await session.delete(meal)
    await session.commit()


def yesterday_utc() -> datetime:
    """Граница «последние сутки» — пригодится для сводок и стрика."""
    return datetime.now(timezone.utc) - timedelta(days=1)
