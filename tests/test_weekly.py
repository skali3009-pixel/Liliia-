"""Тесты воскресных итогов недели (services/weekly.py)."""

import asyncio
import contextlib
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (Base, BodyMeasurement, GenderEnum, GoalEnum, Meal, MealSourceEnum,
                    MealTypeEnum, User, WaterLog, Workout, WorkoutLog)
from models.workout import LevelEnum, LocationEnum, WorkoutTypeEnum
from services.weekly import (SUMMARY_TIME, SUMMARY_WEEKDAY, WINDOW_DAYS, WeeklySummary,
                             build_summary, render, users_for_summary)

# Воскресенье, 19:00 в Москве (UTC+3).
SUNDAY_UTC = datetime(2026, 9, 6, 16, 0, tzinfo=timezone.utc)
SUNDAY_LOCAL = date(2026, 9, 6)


@contextlib.asynccontextmanager
async def db(**overrides):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        fields = dict(
            id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165, current_weight_kg=70,
            goal=GoalEnum.LOSE_WEIGHT, onboarding_completed=True,
            timezone="Europe/Moscow", daily_calories=1700,
        )
        fields.update(overrides)
        user = User(**fields)
        session.add(user)
        await session.commit()
        yield session, user
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def at(days_ago: int, hour: int = 12) -> datetime:
    """Момент в UTC, попадающий в местные сутки «столько-то дней назад»."""
    local_day = SUNDAY_LOCAL - timedelta(days=days_ago)
    return datetime(local_day.year, local_day.month, local_day.day,
                    hour, 0, tzinfo=timezone.utc) - timedelta(hours=3)


def add_meal(session, *, days_ago, calories=500, hour=12):
    session.add(Meal(
        user_id=1, meal_type=MealTypeEnum.LUNCH, name="Обед",
        weight_g=300, calories=calories, protein_g=20, fat_g=10, carbs_g=50,
        source=MealSourceEnum.TEXT, logged_at=at(days_ago, hour),
    ))


def add_weight(session, *, days_ago, kg):
    session.add(BodyMeasurement(user_id=1, weight_kg=kg, measured_at=at(days_ago)))


async def add_workout(session, *, days_ago):
    workout = Workout(
        name="Приседания", workout_type=WorkoutTypeEnum.STRENGTH,
        location=LocationEnum.HOME, level=LevelEnum.BEGINNER, met_value=5.0,
    )
    session.add(workout)
    await session.flush()
    session.add(WorkoutLog(user_id=1, workout_id=workout.id, completed_at=at(days_ago)))


def test_counts_only_the_days_with_records():
    """Пропущенный день не должен считаться днём голодания и занижать среднее."""
    async def scenario():
        async with db() as (session, user):
            add_meal(session, days_ago=0, calories=1600)
            add_meal(session, days_ago=1, calories=1400)
            add_meal(session, days_ago=1, calories=200)
            await session.commit()

            summary = await build_summary(session, user, today=SUNDAY_LOCAL)
            assert summary.days_logged == 2
            assert summary.avg_calories == 1600
    run(scenario)


def test_last_week_stays_out_of_this_week():
    async def scenario():
        async with db() as (session, user):
            add_meal(session, days_ago=WINDOW_DAYS - 1)
            add_meal(session, days_ago=WINDOW_DAYS)
            await session.commit()

            summary = await build_summary(session, user, today=SUNDAY_LOCAL)
            assert summary.days_logged == 1
    run(scenario)


def test_late_evening_meal_belongs_to_the_local_day():
    """Во Владивостоке ужин в 23:00 — это ещё сегодня, а не завтрашний день."""
    async def scenario():
        async with db(timezone="Asia/Vladivostok") as (session, user):
            session.add(Meal(
                user_id=1, meal_type=MealTypeEnum.DINNER, name="Ужин",
                weight_g=300, calories=600, protein_g=20, fat_g=10, carbs_g=50,
                source=MealSourceEnum.TEXT,
                logged_at=datetime(2026, 9, 6, 13, 30, tzinfo=timezone.utc),
            ))
            await session.commit()

            summary = await build_summary(session, user, today=SUNDAY_LOCAL)
            assert summary.days_logged == 1
    run(scenario)


def test_weight_needs_two_weigh_ins_to_show_a_change():
    async def scenario():
        async with db() as (session, user):
            add_weight(session, days_ago=6, kg=70.4)
            await session.commit()
            summary = await build_summary(session, user, today=SUNDAY_LOCAL)
            assert summary.weight_change is None

            add_weight(session, days_ago=0, kg=69.6)
            await session.commit()
            summary = await build_summary(session, user, today=SUNDAY_LOCAL)
            assert summary.weight_change == -0.8
    run(scenario)


def test_workouts_and_water_are_counted_by_days():
    async def scenario():
        async with db() as (session, user):
            await add_workout(session, days_ago=1)
            await add_workout(session, days_ago=3)
            session.add(WaterLog(user_id=1, amount_ml=250, logged_at=at(1, hour=10)))
            session.add(WaterLog(user_id=1, amount_ml=250, logged_at=at(1, hour=15)))
            session.add(WaterLog(user_id=1, amount_ml=250, logged_at=at(2)))
            await session.commit()

            summary = await build_summary(session, user, today=SUNDAY_LOCAL)
            assert summary.workouts == 2
            assert summary.water_days == 2
    run(scenario)


def test_empty_week_is_not_worth_a_message():
    async def scenario():
        async with db() as (session, user):
            summary = await build_summary(session, user, today=SUNDAY_LOCAL)
            assert summary.is_empty is True
    run(scenario)


def summary(**kwargs) -> WeeklySummary:
    fields = dict(user_id=1, days_logged=5, avg_calories=1620, norm_calories=1700,
                  weight_from=None, weight_to=None, workouts=0, water_days=0)
    fields.update(kwargs)
    return WeeklySummary(**fields)


def test_message_shows_the_week_in_numbers():
    text = render(summary(weight_from=70.4, weight_to=69.6, workouts=3, water_days=4))
    assert "5 из 7" in text
    assert "1620 ккал" in text and "норма 1700" in text
    assert "70.4 → 69.6 кг" in text and "−0.8" in text
    assert "Тренировок: 3" in text
    assert "4 дн." in text


def test_empty_week_message_does_not_scold():
    text = render(summary(days_logged=0, avg_calories=0))
    assert "пусто" in text
    for word in ("должна", "лень", "провал", "стыд"):
        assert word not in text.lower()


def test_weight_moving_the_wrong_way_is_explained_not_judged():
    """Плюс на весах при похудении — повод объяснить, а не обвинить."""
    text = render(summary(weight_from=69.6, weight_to=70.2), goal="lose_weight")
    assert "+0.6" in text
    assert "воды" in text


def test_tiny_change_is_called_a_normal_week():
    text = render(summary(weight_from=70.0, weight_to=69.9), goal="lose_weight")
    assert "почти без изменений" in text
    assert "−0.1" not in text


def test_weight_line_is_skipped_without_data():
    assert "кг" not in render(summary())


@pytest.mark.parametrize("days", [1, 4, 7])
def test_closing_line_never_scolds(days):
    text = render(summary(days_logged=days))
    assert "!" not in text
    for word in ("должна", "обязана", "лень", "провал", "стыд", "оправдани"):
        assert word not in text.lower()


def test_summary_goes_out_on_sunday_evening_local():
    async def scenario():
        async with db() as (session, _):
            due = await users_for_summary(session, now_utc=SUNDAY_UTC)
            assert [u.id for u in due] == [1]
    run(scenario)


@pytest.mark.parametrize("shift", [timedelta(minutes=1), timedelta(hours=1), timedelta(days=1)])
def test_no_summary_at_any_other_moment(shift):
    async def scenario():
        async with db() as (session, _):
            assert await users_for_summary(session, now_utc=SUNDAY_UTC + shift) == []
    run(scenario)


def test_each_timezone_gets_its_own_sunday_evening():
    """19:00 — местные: во Владивостоке это другой момент по UTC."""
    async def scenario():
        async with db(timezone="Asia/Vladivostok") as (session, _):
            assert await users_for_summary(session, now_utc=SUNDAY_UTC) == []
            vladivostok = datetime(2026, 9, 6, 9, 0, tzinfo=timezone.utc)
            assert [u.id for u in await users_for_summary(session, now_utc=vladivostok)] == [1]
    run(scenario)


def test_schedule_is_sunday_evening():
    assert SUMMARY_WEEKDAY == 6
    assert (SUMMARY_TIME.hour, SUMMARY_TIME.minute) == (19, 0)


def test_switched_off_reminders_stop_the_weekly_summary():
    async def scenario():
        async with db(reminders_enabled=False) as (session, _):
            assert await users_for_summary(session, now_utc=SUNDAY_UTC) == []
    run(scenario)
