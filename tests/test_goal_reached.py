"""Момент, когда человек дошёл до цели.

Раньше в этот день не происходило ничего: приложение молча продолжало
считать дефицит. Это не только обидно. Норма калорий считается под цель, и
пока в анкете стоит «похудение», человек остаётся в дефиците после того, как
худеть уже некуда, — так и уезжают в недоедание, не сорвавшись, а
старательно продолжая делать то, что говорит приложение.
"""

import asyncio
import contextlib

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (ActivityLevelEnum, Base, GenderEnum, GoalEnum, User)
from services import goal as goal_service

USER = 1


def make(goal=GoalEnum.LOSE_WEIGHT, weight=63.0, target=63.0) -> User:
    return User(id=USER, gender=GenderEnum.FEMALE, age=30, height_cm=165,
                current_weight_kg=weight, target_weight_kg=target, goal=goal,
                activity_level=ActivityLevelEnum.MODERATE,
                onboarding_completed=True, timezone="Europe/Moscow")


# --- Когда считаем, что дошёл ----------------------------------------------

def test_losing_weight_finishes_at_the_target():
    assert goal_service.reached(make(weight=63.0), 63.0)
    assert goal_service.reached(make(weight=62.0), 62.0)
    assert not goal_service.reached(make(weight=65.0), 65.0)


def test_the_scales_wobble_and_that_is_allowed():
    """Весы за день гуляют на полкило от воды и соли."""
    assert goal_service.reached(make(), 63.0 + goal_service.TOLERANCE_KG)
    assert not goal_service.reached(make(), 63.0 + goal_service.TOLERANCE_KG + 0.5)


def test_gaining_mass_finishes_from_the_other_side():
    user = make(goal=GoalEnum.GAIN_MASS, target=70.0)
    assert goal_service.reached(user, 70.0)
    assert goal_service.reached(user, 72.0)
    assert not goal_service.reached(user, 66.0)


def test_maintenance_has_no_finish_line():
    """У поддержания число на весах не финиш — объявлять там победу не о чем."""
    assert not goal_service.reached(make(goal=GoalEnum.MAINTAIN), 63.0)
    assert not goal_service.reached(make(goal=GoalEnum.RECOMPOSITION), 63.0)


def test_without_a_target_there_is_nothing_to_reach():
    assert not goal_service.reached(make(target=None), 63.0)
    assert not goal_service.reached(make(), None)


# --- Что говорим -----------------------------------------------------------

def test_the_words_name_the_road_and_the_danger():
    text = goal_service.render(goal_service.Arrival(
        weight_kg=63.0, target_kg=63.0, started_kg=72.0))

    assert "72" in text and "63" in text and "9" in text
    # Главное — не поздравление, а предупреждение про дефицит после финиша.
    assert "дефицит" in text and "поддержание" in text


def test_nobody_is_pushed_for_another_five_kilograms():
    """Приложение, которое после цели говорит «а теперь ещё», — вредное."""
    text = goal_service.render(goal_service.Arrival(
        weight_kg=63.0, target_kg=63.0, started_kg=72.0)).lower()
    for push in ("а теперь ещё", "продолжаем худеть", "новая цель —",
                 "не останавливайся"):
        assert push not in text, push


def test_a_short_road_is_not_turned_into_a_big_number():
    text = goal_service.render(goal_service.Arrival(
        weight_kg=63.0, target_kg=63.0, started_kg=63.2))
    assert "кг пути" not in text


# --- Награда ---------------------------------------------------------------

def test_the_award_exists_and_is_earned_only_at_the_finish():
    from utils.game import ACHIEVEMENT_BY_CODE, earned_codes

    assert "goal_reached" in ACHIEVEMENT_BY_CODE
    base = dict(meals_total=0, streak=0, level=1, weight_lost_kg=0,
                waist_lost_cm=0, workouts_total=0)
    assert "goal_reached" in earned_codes(**base, goal_reached=True)
    assert "goal_reached" not in earned_codes(**base)


# --- Один раз, а не каждое взвешивание -------------------------------------

@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(make(weight=72.0))
        await session.commit()
        yield session
    await engine.dispose()


def test_the_congratulation_comes_once_not_at_every_weighing():
    """Поздравление на каждом взвешивании — шум, а вопрос про поддержание —
    назойливость."""
    async def scenario():
        from webapp.api import _arrival
        from services.gamification import sync_today
        from services.progress import add_measurement

        async with db() as session:
            user = await session.get(User, USER)
            await add_measurement(session, user=user, weight_kg=63.0)

            first = await _arrival(session, user)
            assert first is not None and "поддержание" in first["text"]

            # Награда выдаётся при следующем пересчёте игры — после неё
            # приложение об этом больше не заговаривает.
            await sync_today(session, user, meals_count=0, calories=0,
                             fiber_g=0, water_ml=0)
            await add_measurement(session, user=user, weight_kg=62.8)
            assert await _arrival(session, user) is None
    run(scenario)


def test_someone_still_on_the_way_hears_nothing():
    async def scenario():
        from webapp.api import _arrival
        from services.progress import add_measurement

        async with db() as session:
            user = await session.get(User, USER)
            await add_measurement(session, user=user, weight_kg=68.0)
            assert await _arrival(session, user) is None
    run(scenario)


def run(scenario):
    asyncio.run(scenario())
