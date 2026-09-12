"""Тесты списка «ешь как обычно»."""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, GenderEnum, GoalEnum, Meal, MealSourceEnum, MealTypeEnum, User
from services.favorites import frequent_meals, normalize

NOW = datetime.now(timezone.utc)


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(
            id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165, current_weight_kg=62,
            goal=GoalEnum.LOSE_WEIGHT, onboarding_completed=True, timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


def add(session, name, *, days_ago=0, calories=200, weight=150):
    session.add(Meal(
        user_id=1, meal_type=MealTypeEnum.BREAKFAST, name=name,
        weight_g=weight, calories=calories, protein_g=10, fat_g=5, carbs_g=20,
        fiber_g=3, source=MealSourceEnum.TEXT,
        logged_at=NOW - timedelta(days=days_ago, minutes=days_ago),
    ))


def test_frequent_meal_is_offered():
    async def scenario():
        async with db() as session:
            for day in (1, 2, 3):
                add(session, "Овсянка", days_ago=day)
            add(session, "Пицца", days_ago=4)
            await session.commit()

            items = await frequent_meals(session, 1)
            assert [i.name for i in items] == ["Овсянка"]
            assert items[0].times == 3
    asyncio.run(scenario())


def test_one_off_meal_is_not_a_habit():
    async def scenario():
        async with db() as session:
            add(session, "Торт на дне рождения", days_ago=3)
            await session.commit()
            assert await frequent_meals(session, 1) == []
    asyncio.run(scenario())


def test_same_dish_written_differently_is_one_item():
    async def scenario():
        async with db() as session:
            add(session, "Овсянка", days_ago=3)
            add(session, "овсянка", days_ago=2)
            add(session, "  Овсянка  ", days_ago=1)
            await session.commit()

            items = await frequent_meals(session, 1)
            assert len(items) == 1 and items[0].times == 3
    asyncio.run(scenario())


def test_last_portion_wins():
    """Поправила вес в прошлый раз — значит, повторять надо этот вес."""
    async def scenario():
        async with db() as session:
            add(session, "Творог", days_ago=5, weight=100, calories=120)
            add(session, "Творог", days_ago=1, weight=200, calories=240)
            await session.commit()

            item = (await frequent_meals(session, 1))[0]
            assert item.weight_g == 200 and item.calories == 240
    asyncio.run(scenario())


def test_more_often_comes_first():
    async def scenario():
        async with db() as session:
            for day in range(1, 6):
                add(session, "Кофе", days_ago=day)
            add(session, "Яйца", days_ago=1)
            add(session, "Яйца", days_ago=2)
            await session.commit()

            assert [i.name for i in await frequent_meals(session, 1)] == ["Кофе", "Яйца"]
    asyncio.run(scenario())


def test_old_meals_drop_out():
    async def scenario():
        async with db() as session:
            add(session, "Забытое", days_ago=200)
            add(session, "Забытое", days_ago=201)
            await session.commit()
            assert await frequent_meals(session, 1) == []
    asyncio.run(scenario())


def test_normalize_ignores_case_and_extra_spaces():
    assert normalize("  Овсянка   с   ягодами ") == "овсянка с ягодами"
    assert normalize(None) == ""
