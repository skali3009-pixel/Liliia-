"""События мира и находки.

Это самая опасная часть приложения: похожие механики легко превращаются в
игровой автомат. Поэтому здесь проверяется не столько то, что награда
начисляется, сколько то, что её нельзя выпросить.
"""

import asyncio
import contextlib
from collections import Counter
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, DayStat, User
from services import events as svc
from utils.events import (EVENT_CHANCE, EVENT_CRYSTALS, EVENT_TARGET, EVENTS,
                          SURPRISE_CHANCE, SURPRISE_CRYSTALS, event_for,
                          surprise_for)
from utils.timeframe import today_in

TZ = "Europe/Moscow"
TODAY = today_in(TZ).isoformat()

# Берём человека, у которого сегодня событие есть, а не пропускаем проверку:
# пропущенный тест ничего не доказывает.
USER_ID = next(uid for uid in range(1, 500) if event_for(uid, TODAY))
LUCKY_ID = next(uid for uid in range(1, 500)
                if event_for(uid, TODAY) and surprise_for(uid, TODAY))
QUIET_ID = next(uid for uid in range(1, 500) if not event_for(uid, TODAY))


@contextlib.asynccontextmanager
async def db(user_id: int = None):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        who = user_id or USER_ID
        session.add(User(id=who, onboarding_completed=True))
        session.add(DayStat(user_id=who, day=today_in(TZ), xp=0,
                            quests_done="", suggested=""))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


# --- Ничего похожего на автомат -------------------------------------------

def test_refreshing_cannot_reroll_the_event():
    """Если обновление меняет исход, появляется смысл «крутить»."""
    day = "2026-09-14"
    first = event_for(USER_ID, day)
    for _ in range(50):
        assert event_for(USER_ID, day) is first


def test_refreshing_cannot_reroll_the_find():
    day = "2026-09-14"
    first = surprise_for(USER_ID, day)
    assert all(surprise_for(USER_ID, day) == first for _ in range(50))


def test_the_reward_is_known_in_advance_and_never_varies():
    """Переменный выигрыш — сердце азартной механики. Здесь его нет."""
    assert {event.crystals for event in EVENTS} == {EVENT_CRYSTALS}
    days = [f"2026-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
    assert set(surprise_for(USER_ID, day) for day in days) <= {0, SURPRISE_CRYSTALS}


def test_a_find_never_comes_out_of_nowhere():
    """Сначала человек что-то делает, и только потом мир его радует."""
    async def scenario():
        async with db() as session:
            assert await svc.surprise(session, USER_ID, closed_now=False,
                                      timezone_name=TZ) == 0
    run(scenario)


def test_nothing_is_ever_taken_away():
    """Событие можно не выполнить — но потерять за это нельзя ничего."""
    async def scenario():
        async with db() as session:
            before = (await session.execute(select(DayStat))).scalar_one().bonus
            await svc.state(session, USER_ID, quests_done=0, timezone_name=TZ)
            after = (await session.execute(select(DayStat))).scalar_one().bonus
            assert after == before == 0
    run(scenario)


# --- Частота ---------------------------------------------------------------

def test_events_are_rare_enough_to_stay_events():
    days = [f"2026-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
    counted = Counter(bool(event_for(uid, day))
                      for uid in range(1, 60) for day in days)
    share = counted[True] / sum(counted.values())
    assert abs(share - EVENT_CHANCE) < 0.05, f"событий {share:.0%}"


def test_finds_are_rarer_still():
    days = [f"2026-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
    share = sum(1 for uid in range(1, 60) for day in days
                if surprise_for(uid, day)) / (59 * len(days))
    assert abs(share - SURPRISE_CHANCE) < 0.05, f"находок {share:.0%}"


def test_different_people_get_different_days():
    """Иначе это не событие мира, а объявление для всех сразу."""
    day = "2026-09-20"
    outcomes = {bool(event_for(uid, day)) for uid in range(1, 40)}
    assert outcomes == {True, False}


# --- Начисление ------------------------------------------------------------

def test_the_event_pays_once_and_only_once():
    async def scenario():
        async with db() as session:
            first = await svc.state(session, USER_ID, EVENT_TARGET, timezone_name=TZ)
            assert first.complete and first.rewarded

            row = (await session.execute(select(DayStat))).scalar_one()
            assert row.bonus == EVENT_CRYSTALS

            for _ in range(4):
                await svc.state(session, USER_ID, EVENT_TARGET, timezone_name=TZ)
            row = (await session.execute(select(DayStat))).scalar_one()
            assert row.bonus == EVENT_CRYSTALS, "заплатили дважды за одно и то же"
    run(scenario)


def test_an_unfinished_event_pays_nothing():
    async def scenario():
        async with db() as session:
            state = await svc.state(session, USER_ID, EVENT_TARGET - 1, timezone_name=TZ)
            assert not state.complete and not state.rewarded
            assert (await session.execute(select(DayStat))).scalar_one().bonus == 0
    run(scenario)


def test_a_find_pays_once_a_day():
    async def scenario():
        async with db(LUCKY_ID) as session:
            first = await svc.surprise(session, LUCKY_ID, closed_now=True,
                                       timezone_name=TZ)
            assert first == SURPRISE_CRYSTALS
            for _ in range(5):
                assert await svc.surprise(session, LUCKY_ID, closed_now=True,
                                          timezone_name=TZ) == 0
    run(scenario)


def test_a_quiet_day_has_no_event_at_all():
    """Событие каждый день перестаёт быть событием."""
    async def scenario():
        async with db(QUIET_ID) as session:
            assert await svc.state(session, QUIET_ID, quests_done=7,
                                   timezone_name=TZ) is None
    run(scenario)


def test_bonus_survives_the_daily_recount():
    """Кристаллы за задания пересчитываются каждый раз и затёрли бы бонус."""
    async def scenario():
        async with db() as session:
            row = (await session.execute(select(DayStat))).scalar_one()
            row.bonus = 20
            row.xp = 30
            await session.commit()

            from services.gamification import _upsert_day

            await _upsert_day(session, USER_ID, today_in(TZ), 45, ["meals"])
            await session.commit()

            row = (await session.execute(select(DayStat))).scalar_one()
            assert row.xp == 45
            assert row.bonus == 20, "пересчёт заданий съел бонус"
    run(scenario)


# --- Тон -------------------------------------------------------------------

@pytest.mark.parametrize("event", EVENTS)
def test_events_ask_for_useful_things_and_do_not_pressure(event):
    text = f"{event.title} {event.text}".lower()
    assert event.target == EVENT_TARGET
    for wrong in ("успей", "срочно", "последний шанс", "потеряешь", "сгорит"):
        assert wrong not in text, f"давление в тексте: {event.title}"
