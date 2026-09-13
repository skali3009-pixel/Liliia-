"""Письмо тому, кто перестал заходить.

Проверяется в основном не текст, а сдержанность: кому НЕ пишем и сколько
раз молчим. Приложение про еду, которое пишет каждую неделю «мы скучаем»,
человек выключает — и тогда не помогает уже ничем.
"""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (Base, BodyMeasurement, GenderEnum, GoalEnum, Meal, MealSourceEnum,
                    MealTypeEnum, User, WaterLog)
from services import comeback

# 12:00 в Москве (UTC+3) — момент рассылки.
MOMENT_UTC = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)


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
        created_at=MOMENT_UTC - timedelta(days=40),
    )
    return User(**{**defaults, **kwargs})


def meal(user_id: int, days_ago: float) -> Meal:
    return Meal(user_id=user_id, meal_type=MealTypeEnum.BREAKFAST, name="Овсянка",
                weight_g=200, calories=250, protein_g=8, fat_g=5, carbs_g=40,
                source=MealSourceEnum.TEXT,
                logged_at=MOMENT_UTC - timedelta(days=days_ago))


def run(scenario):
    asyncio.run(scenario())


# --- Кому пишем ------------------------------------------------------------

def test_writes_on_the_third_silent_day():
    async def scenario():
        async with db() as session:
            session.add(make_user(1))
            session.add(meal(1, 3))
            await session.commit()

            letters = await comeback.due(session, now_utc=MOMENT_UTC)
            assert [item.user_id for item in letters] == [1]
            assert letters[0].days == 3 and letters[0].started
    run(scenario)


def test_writes_again_on_the_tenth_day_and_never_after():
    async def scenario():
        async with db() as session:
            for user_id, days in ((1, 10), (2, 11), (3, 30), (4, 200)):
                session.add(make_user(user_id))
                session.add(meal(user_id, days))
            await session.commit()

            letters = await comeback.due(session, now_utc=MOMENT_UTC)
            assert [item.user_id for item in letters] == [1]
    run(scenario)


def test_silent_on_every_day_between_the_two_letters():
    """Два письма за отсутствие — и всё. Остальные дни человек не слышит ничего."""
    async def scenario():
        async with db() as session:
            for user_id, days in enumerate(range(4, 10), start=1):
                session.add(make_user(user_id))
                session.add(meal(user_id, days))
            await session.commit()

            assert await comeback.due(session, now_utc=MOMENT_UTC) == []
    run(scenario)


def test_silent_for_someone_who_was_here_yesterday():
    async def scenario():
        async with db() as session:
            for user_id, days in ((1, 0), (2, 1), (3, 2)):
                session.add(make_user(user_id))
                session.add(meal(user_id, days))
            await session.commit()

            assert await comeback.due(session, now_utc=MOMENT_UTC) == []
    run(scenario)


def test_any_trace_counts_not_only_food():
    """Человек всю неделю отмечал воду — писать ему «тебя не было» нельзя."""
    async def scenario():
        async with db() as session:
            session.add(make_user(1))
            session.add(meal(1, 3))
            session.add(WaterLog(user_id=1, amount_ml=250,
                                 logged_at=MOMENT_UTC - timedelta(hours=20)))
            session.add(make_user(2))
            session.add(meal(2, 3))
            session.add(BodyMeasurement(user_id=2, weight_kg=61,
                                        measured_at=MOMENT_UTC - timedelta(hours=20)))
            await session.commit()

            assert await comeback.due(session, now_utc=MOMENT_UTC) == []
    run(scenario)


def test_never_writes_to_someone_who_switched_reminders_off():
    async def scenario():
        async with db() as session:
            session.add(make_user(1, reminders_enabled=False))
            session.add(meal(1, 3))
            await session.commit()

            assert await comeback.due(session, now_utc=MOMENT_UTC) == []
    run(scenario)


def test_never_writes_to_someone_still_in_the_questionnaire():
    async def scenario():
        async with db() as session:
            session.add(make_user(1, onboarding_completed=False))
            session.add(meal(1, 3))
            await session.commit()

            assert await comeback.due(session, now_utc=MOMENT_UTC) == []
    run(scenario)


def test_writes_only_at_local_noon():
    async def scenario():
        async with db() as session:
            session.add(make_user(1))
            session.add(meal(1, 3))
            await session.commit()

            for shift in (-3, -1, 1, 5, 9):
                moment = MOMENT_UTC + timedelta(hours=shift)
                assert await comeback.due(session, now_utc=moment) == [], shift
    run(scenario)


def test_a_different_timezone_gets_its_own_noon():
    async def scenario():
        async with db() as session:
            session.add(make_user(1, timezone="Asia/Vladivostok"))
            session.add(meal(1, 3))
            await session.commit()

            # Во Владивостоке (UTC+10) полдень наступает на семь часов раньше.
            assert await comeback.due(session, now_utc=MOMENT_UTC) == []
            early = MOMENT_UTC - timedelta(hours=7)
            assert [i.user_id for i in await comeback.due(session, now_utc=early)] == [1]
    run(scenario)


# --- Кто ещё не начинал ----------------------------------------------------

def test_someone_who_never_logged_anything_is_counted_from_registration():
    async def scenario():
        async with db() as session:
            session.add(make_user(1, created_at=MOMENT_UTC - timedelta(days=3)))
            session.add(make_user(2, created_at=MOMENT_UTC - timedelta(days=1)))
            await session.commit()

            letters = await comeback.due(session, now_utc=MOMENT_UTC)
            assert [item.user_id for item in letters] == [1]
            assert letters[0].started is False
    run(scenario)


# --- Что написано ----------------------------------------------------------

def test_the_letter_never_reproaches_or_counts_days():
    """Ни упрёка, ни цифр про тело — иначе бота просто выключат."""
    forbidden = ("пропустил", "пропустила", "давно", "скучаем", "срыв", "кг",
                 "калори", "вес ", "не заходил")
    for days in comeback.STAGES:
        for started in (True, False):
            text = comeback.render(days, started=started, zones_open=3).lower()
            for word in forbidden:
                assert word not in text, (days, started, word)


def test_the_last_letter_says_it_is_the_last_and_shows_the_way_out():
    for started in (True, False):
        text = comeback.render(comeback.AWAY_SECOND, started=started, zones_open=2)
        assert "последнее" in text.lower() or "больше не" in text.lower()
        assert "Профиль" in text


def test_the_first_letter_leans_on_what_is_already_open():
    text = comeback.render(comeback.AWAY_FIRST, started=True, zones_open=4)
    assert "4" in text
    # А если открывать ещё нечего — просто нет этой строки, без «0 мест».
    assert "0" not in comeback.render(comeback.AWAY_FIRST, started=True, zones_open=0)


def test_the_letter_for_someone_who_never_started_asks_for_one_small_thing():
    text = comeback.render(comeback.AWAY_FIRST, started=False, zones_open=0)
    assert "фотограф" in text.lower()
    assert "мире открыто" not in text


def test_the_world_is_mentioned_only_to_someone_who_has_seen_it():
    """Мир живёт в приложении: тому, кто вёл дневник в чате, он ничего не скажет."""
    from models import DayStat

    async def scenario():
        async with db() as session:
            for user_id in (1, 2):
                session.add(make_user(user_id))
                session.add(meal(user_id, 3))
            # Второй заходил в «Мой мир» — у него там уже что-то открыто.
            session.add(DayStat(user_id=2, day=(MOMENT_UTC - timedelta(days=3)).date(),
                                world_open=2))
            await session.commit()

            letters = {item.user_id: item for item in
                       await comeback.due(session, now_utc=MOMENT_UTC)}
            assert letters[1].zones_open == 0
            assert "мире открыто" not in letters[1].text
            assert letters[2].zones_open > 0
            assert "мире открыто" in letters[2].text
    run(scenario)
