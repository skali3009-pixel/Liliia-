"""Тесты напоминания «сегодня ещё нет ни одной записи о еде»."""

import asyncio
import contextlib
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (Base, GenderEnum, GoalEnum, Meal, MealSourceEnum, MealTypeEnum, User)
from services.meal_reminders import users_without_meals_today

# 20:00 в Москве (UTC+3) — момент срабатывания.
MOMENT_UTC = datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc)


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        yield session
    await engine.dispose()


def make_user(id_, **kwargs) -> User:
    defaults = dict(
        id=id_, gender=GenderEnum.FEMALE, age=30, height_cm=165, current_weight_kg=62,
        goal=GoalEnum.LOSE_WEIGHT, onboarding_completed=True, timezone="Europe/Moscow",
    )
    return User(**{**defaults, **kwargs})


def test_nudges_user_with_empty_diary_at_local_evening():
    async def scenario():
        async with db() as session:
            session.add(make_user(1))
            await session.commit()

            nudges = await users_without_meals_today(session, now_utc=MOMENT_UTC)
            assert [n.user_id for n in nudges] == [1]
    asyncio.run(scenario())


def test_no_nudge_when_meal_already_logged_today():
    async def scenario():
        async with db() as session:
            session.add(make_user(1))
            session.add(Meal(
                user_id=1, meal_type=MealTypeEnum.BREAKFAST, name="Овсянка",
                weight_g=200, calories=250, protein_g=8, fat_g=5, carbs_g=40,
                source=MealSourceEnum.TEXT, logged_at=MOMENT_UTC,
            ))
            await session.commit()

            nudges = await users_without_meals_today(session, now_utc=MOMENT_UTC)
            assert nudges == []
    asyncio.run(scenario())


def test_no_nudge_outside_the_local_reminder_minute():
    async def scenario():
        async with db() as session:
            session.add(make_user(1))
            await session.commit()

            other_moment = MOMENT_UTC.replace(hour=10)  # 13:00 в Москве
            nudges = await users_without_meals_today(session, now_utc=other_moment)
            assert nudges == []
    asyncio.run(scenario())


def test_ignores_users_who_never_finished_onboarding():
    async def scenario():
        async with db() as session:
            session.add(make_user(1, onboarding_completed=False))
            await session.commit()

            nudges = await users_without_meals_today(session, now_utc=MOMENT_UTC)
            assert nudges == []
    asyncio.run(scenario())
