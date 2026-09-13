"""Итог недели по шагам.

Таблица сама по себе не работает: её видит только тот, кто зашёл посмотреть,
а заходить незачем — цифры те же, что вчера. Работает круг: неделя началась,
закрылась, объявили результат, счёт с нуля.

Проверяется в основном сдержанность: кому НЕ пишем и чего в письме нет.
"""

import asyncio
import contextlib
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import ActivityLevelEnum, Base, GenderEnum, GoalEnum, User
from services import step_results
from services import steps as step_service
from services import teams

# Понедельник 7 сентября 2026, 10:00 в Москве (UTC+3).
MONDAY = date(2026, 9, 7)
MOMENT_UTC = datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc)
# Прошлая неделя: 31 августа — 6 сентября.
LAST_MONDAY = date(2026, 8, 31)


@contextlib.asynccontextmanager
async def db(people=(1,)):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for index, user_id in enumerate(people):
            session.add(User(
                id=user_id, full_name=f"Человек{index} Фамилия",
                gender=GenderEnum.FEMALE, age=30, height_cm=165,
                current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                activity_level=ActivityLevelEnum.MODERATE, daily_steps=8000,
                onboarding_completed=True, timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


async def week(session, user_id, start, per_day):
    for shift in range(7):
        await step_service.record(session, user_id, per_day,
                                  day=start + timedelta(days=shift))


# --- Границы недели --------------------------------------------------------

def test_the_result_covers_the_week_that_just_ended():
    async def scenario():
        async with db() as session:
            await week(session, 1, LAST_MONDAY, 9000)
            # Сегодняшний понедельник — уже новая неделя, в итог не идёт.
            await step_service.record(session, 1, 30000, day=MONDAY)

            user = await session.get(User, 1)
            result = await step_results.for_user(session, user, today=MONDAY)
            assert result.steps == 9000 * 7
            assert result.days_done == 7
    run(scenario)


def test_the_week_before_is_shown_to_compare_with():
    async def scenario():
        async with db() as session:
            await week(session, 1, LAST_MONDAY, 9000)
            await week(session, 1, LAST_MONDAY - timedelta(days=7), 5000)

            user = await session.get(User, 1)
            result = await step_results.for_user(session, user, today=MONDAY)
            assert result.previous == 5000 * 7
            assert f"{5000 * 7}" in step_results.render(result)
    run(scenario)


# --- Что в письме ----------------------------------------------------------

def test_the_letter_reports_numbers_not_verdicts():
    """Упрёк от приложения про еду и вес заканчивается тем, что его удаляют."""
    result = step_results.Result(user_id=1, steps=30000, days_done=2, goal=8000,
                                 previous=52000, place=9, people=10)
    text = step_results.render(result).lower()
    for word in ("меньше", "хуже", "провал", "лениш", "стыд", "всего лишь"):
        assert word not in text, word
    assert "30000" in text and "52000" in text


def test_the_letter_uses_proper_russian_for_days():
    def days(count: int) -> str:
        return step_results.render(step_results.Result(
            user_id=1, steps=9000, days_done=count, goal=8000, previous=0,
            place=1, people=1))

    assert "1 день из 7" in days(1)
    assert "2 дня из 7" in days(2)
    assert "5 дней из 7" in days(5)


def test_the_team_line_appears_only_when_there_is_a_team():
    base = dict(user_id=1, steps=9000, days_done=1, goal=8000, previous=0,
                place=1, people=1)
    assert "Команда" not in step_results.render(step_results.Result(**base))
    with_team = step_results.Result(**base, team_name="Лисы", team_total=40000,
                                    team_place=2, team_people=3)
    text = step_results.render(with_team)
    assert "«Лисы»" in text and "40000" in text and "2-я из 3" in text


def test_a_lone_walker_is_not_told_he_is_first_of_one():
    """«Ты первая из одной» звучит как насмешка."""
    result = step_results.Result(user_id=1, steps=9000, days_done=1, goal=8000,
                                 previous=0, place=1, people=1)
    assert "приложению" not in step_results.render(result)


# --- Кому отправляем -------------------------------------------------------

def test_the_result_goes_out_on_monday_morning():
    async def scenario():
        async with db() as session:
            await week(session, 1, LAST_MONDAY, 9000)

            results = await step_results.due(session, now_utc=MOMENT_UTC)
            assert [item.user_id for item in results] == [1]
    run(scenario)


def test_nothing_goes_out_on_other_days_or_hours():
    async def scenario():
        async with db() as session:
            await week(session, 1, LAST_MONDAY, 9000)

            for shift in (timedelta(days=1), timedelta(days=-1),
                          timedelta(hours=1), timedelta(hours=-2)):
                assert await step_results.due(session,
                                              now_utc=MOMENT_UTC + shift) == [], shift
    run(scenario)


def test_someone_who_did_not_walk_is_not_told_he_is_last():
    """«Ты прошла 0 шагов, ты последняя» — это не итог, а пинок."""
    async def scenario():
        async with db(people=(1, 2)) as session:
            await week(session, 2, LAST_MONDAY, 9000)

            results = await step_results.due(session, now_utc=MOMENT_UTC)
            assert [item.user_id for item in results] == [2]
    run(scenario)


def test_someone_who_switched_reminders_off_gets_nothing():
    async def scenario():
        async with db() as session:
            user = await session.get(User, 1)
            user.reminders_enabled = False
            await week(session, 1, LAST_MONDAY, 9000)

            assert await step_results.due(session, now_utc=MOMENT_UTC) == []
    run(scenario)


def test_the_team_standing_is_counted_inside_the_team():
    async def scenario():
        async with db(people=(1, 2, 3)) as session:
            _, team = await teams.create(session, 1, "Лисы")
            for user_id in (2, 3):
                await teams.join(session, user_id, team.code)

            await week(session, 1, LAST_MONDAY, 5000)
            await week(session, 2, LAST_MONDAY, 12000)
            await week(session, 3, LAST_MONDAY, 9000)

            user = await session.get(User, 1)
            result = await step_results.for_user(session, user, today=MONDAY)
            assert result.team_name == "Лисы"
            assert result.team_total == (5000 + 12000 + 9000) * 7
            assert result.team_place == 3 and result.team_people == 3
    run(scenario)


def test_a_week_without_a_single_goal_offers_a_smaller_goal():
    """Цель, которую не взяли ни разу, чаще великовата, чем человек ленив."""
    result = step_results.Result(user_id=1, steps=36500, days_done=0, goal=12000,
                                 previous=0, place=3, people=3)
    text = step_results.render(result)
    assert "0 дней" not in text
    assert "36500" in text
    assert "12000" in text and "великовата" in text
    assert "профиле" in text
