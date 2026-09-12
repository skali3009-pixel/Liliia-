"""Мои заготовки: что в холодильнике и что портится сегодня.

Справочник отвечает, сколько хранится борщ. Здесь — что борщ есть у тебя и
что его пора съесть. Без второго «использовать заготовки при подборе» —
пустые слова: непонятно, из чего собирать.
"""

import asyncio
import contextlib
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, User
from services import preps as svc
from utils.timeframe import today_in

USER_ID = 71
TZ = "Europe/Moscow"


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(id=USER_ID, onboarding_completed=True))
        await session.commit()
        from seed.nutrition.loader import seed_nutrition

        await seed_nutrition(session)
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


# --- Сроки из её же формулировок -------------------------------------------

@pytest.mark.parametrize("text,days", [
    ("3 дня", 3),
    ("3–4 дня", 3),                     # из «три-четыре» безопаснее услышать три
    ("4–5 дней; лучше в стекле", 4),
    ("", svc.DEFAULT_FRIDGE_DAYS),
    (None, svc.DEFAULT_FRIDGE_DAYS),
])
def test_shelf_life_is_read_from_her_own_words(text, days):
    assert svc.shelf_days(text) == days


# --- Холодильник -----------------------------------------------------------

def test_marking_a_prep_puts_it_in_the_fridge():
    async def scenario():
        async with db() as session:
            assert await svc.mine(session, USER_ID) == []

            code = (await _any_code(session))
            await svc.mark_made(session, USER_ID, code, timezone_name=TZ)

            fridge = await svc.mine(session, USER_ID, timezone_name=TZ)
            assert [item.code for item in fridge] == [code]
            assert fridge[0].days_left >= 1
            assert not fridge[0].expiring
    run(scenario)


def test_eating_it_empties_the_fridge():
    async def scenario():
        async with db() as session:
            code = await _any_code(session)
            await svc.mark_made(session, USER_ID, code, timezone_name=TZ)
            await svc.forget(session, USER_ID, code)
            assert await svc.mine(session, USER_ID) == []
    run(scenario)


def test_cooking_the_same_thing_again_resets_the_clock():
    """Люди готовят одно и то же не раз — вторая отметка не должна дублировать."""
    async def scenario():
        async with db() as session:
            code = await _any_code(session)
            await svc.mark_made(session, USER_ID, code, timezone_name=TZ)
            await _age(session, code, days=5)
            await svc.mark_made(session, USER_ID, code, timezone_name=TZ)

            fridge = await svc.mine(session, USER_ID, timezone_name=TZ)
            assert len(fridge) == 1
            assert fridge[0].made_on == today_in(TZ)
            assert not fridge[0].gone
    run(scenario)


def test_what_expires_today_is_named_so():
    async def scenario():
        async with db() as session:
            code = await _any_code(session)
            await svc.mark_made(session, USER_ID, code, timezone_name=TZ)
            # Состариваем ровно до последнего дня.
            from services.preps import shelf_days
            from models import Prep
            from sqlalchemy import select

            prep = (await session.execute(
                select(Prep).where(Prep.code == code))).scalar_one()
            await _age(session, code, days=shelf_days(prep.fridge_days))

            fridge = await svc.mine(session, USER_ID, timezone_name=TZ)
            assert fridge[0].expiring and not fridge[0].gone
            assert "сегодня" in fridge[0].hint

            names = await svc.expiring_names(session, USER_ID, timezone_name=TZ)
            assert names == (prep.name,)
    run(scenario)


def test_expired_is_shown_but_marked():
    """Молча прятать испортившееся нельзя: человек будет искать его глазами."""
    async def scenario():
        async with db() as session:
            code = await _any_code(session)
            await svc.mark_made(session, USER_ID, code, timezone_name=TZ)
            await _age(session, code, days=30)

            fridge = await svc.mine(session, USER_ID, timezone_name=TZ)
            assert fridge[0].gone
            assert "не рисковать" in fridge[0].hint
            # И в подсказки «съешь сегодня» оно уже не попадает.
            assert await svc.expiring_names(session, USER_ID, timezone_name=TZ) == ()
    run(scenario)


def test_the_soonest_comes_first():
    async def scenario():
        async with db() as session:
            codes = await _codes(session, 3)
            for code in codes:
                await svc.mark_made(session, USER_ID, code, timezone_name=TZ)
            await _age(session, codes[1], days=2)

            fridge = await svc.mine(session, USER_ID, timezone_name=TZ)
            assert fridge[0].code == codes[1]
            assert fridge == sorted(fridge, key=lambda item: item.days_left)
    run(scenario)


async def _codes(session, count: int) -> list[str]:
    from sqlalchemy import select
    from models import Prep

    return list((await session.execute(
        select(Prep.code).order_by(Prep.code).limit(count))).scalars())


async def _any_code(session) -> str:
    return (await _codes(session, 1))[0]


async def _age(session, code: str, *, days: int) -> None:
    """Сделать вид, что заготовку приготовили несколько дней назад."""
    from sqlalchemy import select
    from models import UserPrep

    row = (await session.execute(
        select(UserPrep).where(UserPrep.prep_code == code))).scalar_one()
    row.made_on = today_in(TZ) - timedelta(days=days)
    await session.commit()
