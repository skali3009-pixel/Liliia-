"""Тесты дневного напоминания про воду."""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, GenderEnum, GoalEnum, User, WaterLog
from services.water_reminders import (BEHIND_SHARE, REMINDER_TIME, WaterNudge, render,
                                      users_behind_on_water)

# 16:00 в Москве (UTC+3).
MOMENT_UTC = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)
NORM = 2000


@contextlib.asynccontextmanager
async def db(**overrides):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        fields = dict(
            id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165, current_weight_kg=62,
            goal=GoalEnum.LOSE_WEIGHT, onboarding_completed=True,
            timezone="Europe/Moscow", daily_water_ml=NORM, reminders_enabled=True,
        )
        fields.update(overrides)
        session.add(User(**fields))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def drink(session, ml, *, at=MOMENT_UTC):
    session.add(WaterLog(user_id=1, amount_ml=ml, logged_at=at))


def test_reminds_the_one_who_is_behind():
    async def scenario():
        async with db() as session:
            drink(session, 400)
            await session.commit()

            nudges = await users_behind_on_water(session, now_utc=MOMENT_UTC)
            assert [(n.user_id, n.drunk_ml, n.left_ml) for n in nudges] == [(1, 400, 1600)]
    run(scenario)


def test_says_nothing_to_the_one_who_drinks():
    """Напоминание тому, кто и так пьёт, — это просто спам."""
    async def scenario():
        async with db() as session:
            drink(session, int(NORM * BEHIND_SHARE))
            await session.commit()
            assert await users_behind_on_water(session, now_utc=MOMENT_UTC) == []
    run(scenario)


def test_yesterday_does_not_count():
    async def scenario():
        async with db() as session:
            drink(session, 2000, at=MOMENT_UTC - timedelta(days=1))
            await session.commit()
            nudges = await users_behind_on_water(session, now_utc=MOMENT_UTC)
            assert [n.drunk_ml for n in nudges] == [0]
    run(scenario)


@pytest.mark.parametrize("shift", [timedelta(minutes=1), timedelta(hours=2)])
def test_only_once_at_the_appointed_minute(shift):
    async def scenario():
        async with db() as session:
            assert await users_behind_on_water(session, now_utc=MOMENT_UTC + shift) == []
    run(scenario)


def test_switched_off_reminders_are_really_off():
    async def scenario():
        async with db(reminders_enabled=False) as session:
            assert await users_behind_on_water(session, now_utc=MOMENT_UTC) == []
    run(scenario)


def test_norm_falls_back_when_it_was_never_calculated():
    async def scenario():
        async with db(daily_water_ml=None) as session:
            nudges = await users_behind_on_water(session, now_utc=MOMENT_UTC)
            assert nudges and nudges[0].norm_ml > 0
    run(scenario)


def test_reminder_is_in_the_middle_of_the_day():
    """Вечером допить норму уже нереально — напоминание станет упрёком."""
    assert 12 <= REMINDER_TIME.hour <= 17


def test_message_without_a_single_glass_does_not_scold():
    text = render(WaterNudge(user_id=1, drunk_ml=0, norm_ml=NORM))
    assert "2000" in text
    assert "!" not in text
    for word in ("должна", "забыла", "опять"):
        assert word not in text.lower()


def test_message_shows_what_is_left():
    text = render(WaterNudge(user_id=1, drunk_ml=600, norm_ml=NORM))
    assert "600" in text and "1400" in text
