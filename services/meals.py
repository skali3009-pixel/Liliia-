"""Работа с приёмами пищи в БД: сохранение и дневные итоги."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Meal, MealSourceEnum, MealTypeEnum
from services.food_vision import FoodAnalysis
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds


@dataclass(frozen=True)
class DayTotals:
    """Сколько уже съедено за сегодня."""

    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float


async def save_meal(
    session: AsyncSession,
    *,
    user_id: int,
    analysis: FoodAnalysis,
    source: MealSourceEnum,
    meal_type: MealTypeEnum,
    photo_file_id: str | None = None,
    logged_at: datetime | None = None,
) -> Meal:
    """Сохранить распознанный приём пищи.

    `logged_at` задаётся, когда человек поправил время момента; иначе время
    ставит база.
    """
    # В базу время кладём в UTC: драйверы по-разному обходятся с зоной,
    # а UTC читается одинаково везде.
    if logged_at is not None and logged_at.tzinfo is not None:
        logged_at = logged_at.astimezone(timezone.utc)

    meal = Meal(
        user_id=user_id,
        meal_type=meal_type,
        name=analysis.name,
        weight_g=analysis.weight_g,
        calories=analysis.calories,
        protein_g=analysis.protein_g,
        fat_g=analysis.fat_g,
        carbs_g=analysis.carbs_g,
        fiber_g=analysis.fiber_g,
        source=source,
        photo_file_id=photo_file_id,
        **({"logged_at": logged_at} if logged_at else {}),
    )
    session.add(meal)
    await session.commit()
    return meal


async def get_today_totals(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> DayTotals:
    """Суммарные КБЖУ за сегодня — по местному времени пользователя."""
    start, end = day_bounds(timezone_name)
    stmt = select(
        func.coalesce(func.sum(Meal.calories), 0.0),
        func.coalesce(func.sum(Meal.protein_g), 0.0),
        func.coalesce(func.sum(Meal.fat_g), 0.0),
        func.coalesce(func.sum(Meal.carbs_g), 0.0),
        func.coalesce(func.sum(Meal.fiber_g), 0.0),
    ).where(Meal.user_id == user_id, Meal.logged_at >= start, Meal.logged_at < end)

    calories, protein_g, fat_g, carbs_g, fiber_g = (await session.execute(stmt)).one()
    return DayTotals(
        calories=float(calories),
        protein_g=float(protein_g),
        fat_g=float(fat_g),
        carbs_g=float(carbs_g),
        fiber_g=float(fiber_g),
    )


async def delete_meal(session: AsyncSession, meal: Meal) -> None:
    """Удалить запись (кнопка «Отменить» сразу после сохранения)."""
    await session.delete(meal)
    await session.commit()


async def list_today_meals(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> list[Meal]:
    """Съеденное за сегодня — по времени записи, от раннего к позднему."""
    start, end = day_bounds(timezone_name)
    stmt = (
        select(Meal)
        .where(Meal.user_id == user_id, Meal.logged_at >= start, Meal.logged_at < end)
        .order_by(Meal.logged_at, Meal.id)
    )
    return list((await session.execute(stmt)).scalars().all())
