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
    logged_at: datetime | None = None,
    from_offer: bool = False,
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
        **({"logged_at": logged_at} if logged_at else {}),
    )
    session.add(meal)
    # Полезное действие отмечается здесь, а не в четырёх обработчиках: это
    # единственное место, где приём пищи правда попадает в дневник — и из
    # чата, и из приложения. Уезжает тем же коммитом: учёт, сохранившийся
    # без действия, — цифра, за которой ничего нет.
    from services import analytics

    await analytics.useful_action(session, user_id, "meal")
    if from_offer:
        await analytics.note(session, user_id, analytics.MEAL_FROM_OFFER)
    await session.commit()
    # Время записи ставит база; без перечитывания оно осталось бы
    # незагруженным, и первое же обращение к нему в async упало бы.
    await session.refresh(meal)
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
    """Удалить запись (кнопка «Отменить» сразу после сохранения).

    Отмена отмечается в учёте отдельным событием, а не вычитается из
    `action_completed`: запись правда была, и счётчик действий не должен
    переписываться задним числом. Зато по двум числам рядом видно, какая
    доля записей оказалась ошибочной, — а это и есть мера доверия к оценке.
    """
    from services import analytics

    await analytics.note(session, meal.user_id, analytics.MEAL_UNDONE)
    await session.delete(meal)
    await session.commit()


async def rescale_meal(session: AsyncSession, meal: Meal, weight_g: float) -> Meal:
    """Поправить вес уже записанной порции; КБЖУ пересчитываются пропорционально.

    Одна дорога для чата и приложения: вторая копия пересчёта однажды
    разошлась бы с первой, и одна и та же правка давала бы разные калории.
    """
    from utils.portions import scale_nutrition

    if not meal.weight_g:
        raise ValueError("У записи не указан вес")
    scaled = scale_nutrition(
        {
            "calories": meal.calories,
            "protein_g": meal.protein_g,
            "fat_g": meal.fat_g,
            "carbs_g": meal.carbs_g,
            "fiber_g": meal.fiber_g or 0,
        },
        from_weight_g=meal.weight_g,
        to_weight_g=weight_g,
    )
    meal.weight_g = weight_g
    meal.calories = scaled["calories"]
    meal.protein_g = scaled["protein_g"]
    meal.fat_g = scaled["fat_g"]
    meal.carbs_g = scaled["carbs_g"]
    meal.fiber_g = scaled["fiber_g"]
    await session.commit()
    return meal


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
