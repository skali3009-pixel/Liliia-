"""Друзья и совместные цели.

Проверяется прежде всего не то, что дружба работает, а то, что она не
протекает. Приложение хранит вес, замеры, фотографии и дневник еды —
и ничего из этого не должно попасть к другому человеку.
"""

import asyncio
import contextlib
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, DayStat, Friendship, User
from services import challenges, friends
from utils.timeframe import today_in

TZ = "Europe/Moscow"
ANNA, MARIA, OLGA = 101, 102, 103


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for uid, name in ((ANNA, "Анна Петрова"), (MARIA, "Мария Иванова"),
                          (OLGA, "Ольга Смирнова")):
            session.add(User(id=uid, full_name=name, onboarding_completed=True,
                             current_weight_kg=70.0, target_weight_kg=62.0))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


async def _earn(session, user_id: int, crystals: int, *, days_ago: int = 0) -> None:
    session.add(DayStat(user_id=user_id, day=today_in(TZ) - timedelta(days=days_ago),
                        xp=crystals, quests_done="meals"))
    await session.commit()


# --- Ничего лишнего наружу -------------------------------------------------

def test_a_friend_sees_only_the_game_layer():
    """Вес, замеры, фото и еда — не то, чем делятся со знакомыми."""
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            await _earn(session, MARIA, 60)

            cards = await friends.board(session, ANNA, timezone_name=TZ)
            maria = next(card for card in cards if card.user_id == MARIA)
            visible = maria.to_dict()

            assert set(visible) == {"user_id", "name", "level", "crystals",
                                    "week", "streak", "me"}
            for leak in ("weight", "waist", "photo", "calories", "meal",
                         "target_weight", "measurement"):
                assert not any(leak in key for key in visible), f"утекло: {leak}"
    run(scenario)


def test_only_the_first_name_is_shown():
    """Фамилия — лишнее: для списка друзей хватает имени."""
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            cards = await friends.board(session, ANNA, timezone_name=TZ)
            names = {card.name for card in cards}
            assert names == {"Анна", "Мария"}
            assert not any("Петрова" in name or "Иванова" in name for name in names)
    run(scenario)


def test_a_stranger_is_not_in_the_list():
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            cards = await friends.board(session, ANNA, timezone_name=TZ)
            assert OLGA not in {card.user_id for card in cards}
    run(scenario)


# --- Приглашения -----------------------------------------------------------

def test_an_invite_is_personal_and_unguessable():
    async def scenario():
        async with db() as session:
            first = await friends.invite_code(session, ANNA)
            second = await friends.invite_code(session, MARIA)
            assert first != second
            assert len(first) >= 6
            # Повторный вызов не плодит новые коды.
            assert await friends.invite_code(session, ANNA) == first
    run(scenario)


def test_renewing_the_link_kills_the_old_one():
    """Так отзывают ссылку, отправленную не туда."""
    async def scenario():
        async with db() as session:
            old = await friends.invite_code(session, ANNA)
            new = await friends.invite_code(session, ANNA, renew=True)
            assert new != old
            assert await friends.owner_of(session, old) is None
            assert await friends.owner_of(session, new) == ANNA
    run(scenario)


def test_you_cannot_befriend_yourself():
    async def scenario():
        async with db() as session:
            assert await friends.connect(session, ANNA, ANNA) == "self"
            assert await friends.count(session, ANNA) == 0
    run(scenario)


def test_friendship_works_both_ways():
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            assert await friends.are_friends(session, ANNA, MARIA)
            assert await friends.are_friends(session, MARIA, ANNA)
    run(scenario)


def test_either_side_can_walk_away():
    """Разрыв не спрашивает второго и не оставляет половину связи."""
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            await friends.disconnect(session, MARIA, ANNA)

            assert not await friends.are_friends(session, ANNA, MARIA)
            assert not await friends.are_friends(session, MARIA, ANNA)
            assert (await session.execute(select(Friendship))).first() is None
    run(scenario)


def test_the_list_has_a_limit():
    async def scenario():
        async with db() as session:
            for extra in range(200, 200 + friends.MAX_FRIENDS):
                session.add(User(id=extra, onboarding_completed=True))
            await session.commit()
            for extra in range(200, 200 + friends.MAX_FRIENDS):
                await friends.connect(session, ANNA, extra)

            assert await friends.connect(session, ANNA, MARIA) == "full"
    run(scenario)


# --- Соревнование ----------------------------------------------------------

def test_the_board_ranks_by_crystals_not_kilograms():
    """Таблица по сброшенному весу — это соревнование по голоданию."""
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            await _earn(session, ANNA, 40)
            await _earn(session, MARIA, 90)

            cards = await friends.board(session, ANNA, timezone_name=TZ)
            assert [card.user_id for card in cards] == [MARIA, ANNA]
            assert cards[0].week_crystals == 90
    run(scenario)


def test_old_crystals_do_not_win_this_week():
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            await _earn(session, ANNA, 500, days_ago=30)
            await _earn(session, MARIA, 30)

            cards = await friends.board(session, ANNA, timezone_name=TZ)
            assert cards[0].user_id == MARIA, "неделя считается за неделю"
            anna = next(card for card in cards if card.user_id == ANNA)
            assert anna.crystals == 500, "общий счёт при этом сохраняется"
    run(scenario)


def test_alone_there_is_no_board():
    async def scenario():
        async with db() as session:
            cards = await friends.board(session, ANNA, timezone_name=TZ)
            assert len(cards) == 1 and cards[0].is_me
    run(scenario)


# --- Совместная цель -------------------------------------------------------

def test_the_goal_is_shared_not_a_race():
    """Складываются вклады всех: выигрывают вместе или никто."""
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            await _earn(session, ANNA, 200)
            await _earn(session, MARIA, 300)

            goal = await challenges.current(session, ANNA, timezone_name=TZ)
            assert goal.people == 2
            assert goal.target == challenges.PER_PERSON * 2
            assert goal.done == 500
            assert goal.complete
    run(scenario)


def test_the_goal_cannot_be_lost():
    """Незакрытая цель просто остаётся незакрытой. Отнимать нечего."""
    async def scenario():
        async with db() as session:
            await friends.connect(session, ANNA, MARIA)
            goal = await challenges.current(session, ANNA, timezone_name=TZ)
            assert goal.done == 0 and not goal.complete
            for word in ("потерял", "провал", "сгорит", "проиграл"):
                assert word not in goal.hint.lower()
    run(scenario)


def test_there_is_no_goal_without_friends():
    async def scenario():
        async with db() as session:
            assert await challenges.current(session, ANNA, timezone_name=TZ) is None
    run(scenario)


def test_the_week_is_monday_to_sunday():
    from datetime import date

    start, end = challenges.week_bounds(date(2026, 9, 10))   # четверг
    assert start == date(2026, 9, 7) and end == date(2026, 9, 13)
    assert start.weekday() == 0 and end.weekday() == 6
