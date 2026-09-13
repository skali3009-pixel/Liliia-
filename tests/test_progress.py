"""Тесты прогресса: стрик и пересчёт нормы при изменении веса."""

import asyncio
import contextlib
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (ActivityLevelEnum, Base, DietTypeEnum, GenderEnum, GoalEnum, User)
from services.progress import add_measurement, compute_streak, measure_points

TODAY = date(2026, 9, 4)


def test_streak_counts_consecutive_days_up_to_today():
    days = {TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=2)}
    assert compute_streak(days, today=TODAY) == 3


def test_streak_survives_empty_today():
    """Утром, до первого приёма пищи, стрик не должен обнуляться."""
    days = {TODAY - timedelta(days=1), TODAY - timedelta(days=2)}
    assert compute_streak(days, today=TODAY) == 2


def test_streak_breaks_on_gap():
    days = {TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=3)}
    assert compute_streak(days, today=TODAY) == 2


def test_streak_is_zero_without_records():
    assert compute_streak(set(), today=TODAY) == 0


def test_streak_ignores_old_history():
    assert compute_streak({TODAY - timedelta(days=10)}, today=TODAY) == 0


@contextlib.asynccontextmanager
async def user_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        user = User(
            id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165, current_weight_kg=62,
            target_weight_kg=56, activity_level=ActivityLevelEnum.MODERATE,
            goal=GoalEnum.LOSE_WEIGHT, diet_type=DietTypeEnum.REGULAR,
            # Норма для 62 кг по формуле Миффлина-Сан Жеора: BMR 1340 →
            # TDEE 2077 → дефицит 20% → 1662 ккал.
            daily_calories=1662, daily_protein_g=124, daily_fat_g=50, daily_carbs_g=150,
            daily_water_ml=2170, onboarding_completed=True, timezone="Europe/Moscow")
        session.add(user)
        await session.commit()
        yield session, user
    await engine.dispose()


def test_new_weight_updates_profile_and_recalculates_norms():
    async def scenario():
        async with user_session() as (session, user):
            before = user.daily_calories
            _, updated = await add_measurement(session, user=user, weight_kg=59.5)

            assert updated is True
            assert user.current_weight_kg == 59.5
            # Похудела на 2.5 кг — норма калорий пересчиталась вниз.
            assert user.daily_calories < before
            assert user.daily_calories == 1631
            assert user.daily_water_ml == round(59.5 * 35)
    asyncio.run(scenario())


def test_measurement_without_weight_keeps_norms():
    async def scenario():
        async with user_session() as (session, user):
            before = user.daily_calories
            _, updated = await add_measurement(session, user=user, waist_cm=72)

            assert updated is False
            assert user.daily_calories == before
    asyncio.run(scenario())


def test_measure_points_returns_one_value_per_day():
    async def scenario():
        async with user_session() as (session, user):
            await add_measurement(session, user=user, weight_kg=62)
            await add_measurement(session, user=user, weight_kg=61.5)  # тот же день

            points = await measure_points(session, user.id, field="weight", days=30,
                                          timezone_name="Europe/Moscow")
            assert len(points) == 1
            assert points[0].value == 61.5  # осталось последнее значение за день
    asyncio.run(scenario())
