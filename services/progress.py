"""Прогресс: динамика веса, объёмов и калорий, замеры, стрик, фото."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import BodyMeasurement, Meal, ProgressPhoto, User
from services.profile import recalculate
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds, get_zone, to_local, today_in

logger = logging.getLogger(__name__)

# Поля замеров, которые показываем на графике и в форме.
# «Бёдра» (таз целиком) и «бедро» (одна нога) на слух почти неразличимы,
# поэтому в заголовках пишем полностью, а в форме замера — с пояснением.
MEASURE_FIELDS = {
    "weight": ("weight_kg", "Вес", "кг"),
    "waist": ("waist_cm", "Обхват талии", "см"),
    "hips": ("hips_cm", "Обхват бёдер", "см"),
    "thigh": ("thigh_cm", "Обхват ноги", "см"),
    "chest": ("chest_cm", "Обхват груди", "см"),
    "arm": ("arm_cm", "Обхват руки", "см"),
}


@dataclass(frozen=True)
class Point:
    day: date
    value: float


def compute_streak(days_with_meals: set[date], *, today: date) -> int:
    """Сколько дней подряд еда записана.

    Сегодняшний день ещё может быть пустым — тогда считаем от вчера, чтобы
    стрик не обнулялся с утра, до первого приёма пищи.
    """
    if not days_with_meals:
        return 0

    cursor = today if today in days_with_meals else today - timedelta(days=1)
    streak = 0
    while cursor in days_with_meals:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


async def measure_points(
    session: AsyncSession,
    user_id: int,
    *,
    field: str = "weight",
    days: int = 30,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> list[Point]:
    """Замеры за период: по одной (последней) точке на день."""
    column_name = MEASURE_FIELDS.get(field, MEASURE_FIELDS["weight"])[0]
    column = getattr(BodyMeasurement, column_name)

    start, _ = day_bounds(timezone_name, day=today_in(timezone_name) - timedelta(days=days - 1))
    rows = (
        (
            await session.execute(
                select(BodyMeasurement)
                .where(
                    BodyMeasurement.user_id == user_id,
                    BodyMeasurement.measured_at >= start,
                    column.is_not(None),
                )
                .order_by(BodyMeasurement.measured_at)
            )
        )
        .scalars()
        .all()
    )

    by_day: dict[date, float] = {}
    for row in rows:
        by_day[to_local(row.measured_at, timezone_name).date()] = float(getattr(row, column_name))
    return [Point(day, value) for day, value in sorted(by_day.items())]


async def latest_measures(session: AsyncSession, user_id: int) -> dict[str, float]:
    """Последнее известное значение по каждому обхвату.

    По каждому полю отдельно: человек редко меряет всё сразу, и талия из
    вчерашней записи не должна пропадать из-за того, что сегодня записан
    только вес.
    """
    rows = (
        (
            await session.execute(
                select(BodyMeasurement)
                .where(BodyMeasurement.user_id == user_id)
                .order_by(BodyMeasurement.measured_at)
            )
        )
        .scalars()
        .all()
    )

    latest: dict[str, float] = {}
    for row in rows:
        for key, (column_name, _, _) in MEASURE_FIELDS.items():
            value = getattr(row, column_name)
            if value is not None:
                latest[key] = float(value)
    return latest


async def calorie_points(
    session: AsyncSession,
    user_id: int,
    *,
    days: int = 30,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> list[Point]:
    """Съеденные калории по дням (дни без записей не показываем)."""
    start, _ = day_bounds(timezone_name, day=today_in(timezone_name) - timedelta(days=days - 1))
    rows = (
        (
            await session.execute(
                select(Meal)
                .where(Meal.user_id == user_id, Meal.logged_at >= start)
                .order_by(Meal.logged_at)
            )
        )
        .scalars()
        .all()
    )

    totals: dict[date, float] = {}
    for meal in rows:
        day = to_local(meal.logged_at, timezone_name).date()
        totals[day] = totals.get(day, 0.0) + float(meal.calories)
    return [Point(day, round(value)) for day, value in sorted(totals.items())]


async def meal_days(
    session: AsyncSession, user_id: int, *, days: int = 60, timezone_name: str = DEFAULT_TIMEZONE
) -> set[date]:
    """Дни, в которые хоть что-то записано — для стрика."""
    return {point.day for point in await calorie_points(
        session, user_id, days=days, timezone_name=timezone_name
    )}


async def add_measurement(
    session: AsyncSession,
    *,
    user: User,
    weight_kg: float | None = None,
    waist_cm: float | None = None,
    hips_cm: float | None = None,
    chest_cm: float | None = None,
    thigh_cm: float | None = None,
    arm_cm: float | None = None,
) -> tuple[BodyMeasurement, bool]:
    """Сохранить замер. Если изменился вес — обновляем профиль и норму КБЖУ.

    Возвращает (замер, пересчитана ли норма).
    """
    measurement = BodyMeasurement(
        user_id=user.id,
        weight_kg=weight_kg,
        waist_cm=waist_cm,
        hips_cm=hips_cm,
        chest_cm=chest_cm,
        thigh_cm=thigh_cm,
        arm_cm=arm_cm,
    )
    session.add(measurement)

    norms_updated = False
    if weight_kg:
        user.current_weight_kg = weight_kg
        # Норму считает profile.recalculate — одна формула на весь проект,
        # чтобы взвешивание и правка анкеты не разъехались в цифрах.
        norms_updated = recalculate(user)

    await session.commit()
    return measurement, norms_updated


def photos_dir(user_id: int) -> Path:
    directory = Path(config.PHOTOS_DIR) / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def save_photo(session: AsyncSession, *, user_id: int, content: bytes) -> ProgressPhoto:
    file_name = f"{uuid.uuid4().hex}.jpg"
    (photos_dir(user_id) / file_name).write_bytes(content)

    photo = ProgressPhoto(user_id=user_id, file_name=file_name)
    session.add(photo)
    await session.commit()
    return photo


async def list_photos(session: AsyncSession, user_id: int) -> list[ProgressPhoto]:
    rows = (
        (
            await session.execute(
                select(ProgressPhoto)
                .where(ProgressPhoto.user_id == user_id, ProgressPhoto.file_name.is_not(None))
                .order_by(ProgressPhoto.taken_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
