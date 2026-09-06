"""Удаление данных: после него человека не должно остаться нигде.

Проверка появилась вместе с командой /delete в меню Telegram: раз о ней
теперь узнают все, она обязана делать ровно то, что обещает. Почти всё
уходит каскадом, но две связи каскадом не описываются — обратная дружба и
команда, — и именно они пережили бы удаление.
"""

import asyncio
import contextlib

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (ActivityLevelEnum, Base, Friendship, GenderEnum, GoalEnum, Meal,
                    MealSourceEnum, MealTypeEnum, StepLog, Team, TeamMember, User)
from services import deletion, friends, steps as step_service, teams


@contextlib.asynccontextmanager
async def db(people=(1, 2, 3)):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        # Без этого SQLite не проверяет внешние ключи и каскад не срабатывает —
        # в PostgreSQL на сервере он работает всегда.
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)

    async with maker() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        for index, user_id in enumerate(people):
            session.add(User(
                id=user_id, full_name=f"Человек{index}", gender=GenderEnum.FEMALE,
                age=30, height_cm=165, current_weight_kg=62,
                goal=GoalEnum.LOSE_WEIGHT, activity_level=ActivityLevelEnum.MODERATE,
                onboarding_completed=True, timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


# --- Схема -----------------------------------------------------------------

def test_every_table_with_the_persons_data_is_wired_to_cascade():
    """Новая таблица без каскада переживёт удаление молча."""
    known_exceptions = {
        # Расход на модель обезличивается, а не удаляется: он нужен для учёта
        # денег, и без него дневной потолок считался бы неверно.
        ("api_usage", "user_id"),
        # Не внешние ключи по устройству: команда переживает своего создателя,
        # обратная дружба убирается руками в services/deletion.py.
        ("teams", "owner_id"),
        ("friendships", "friend_id"),
    }
    problems = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if column.name not in {"user_id", "owner_id", "friend_id"}:
                continue
            if (table.name, column.name) in known_exceptions:
                continue
            keys = list(column.foreign_keys)
            if not keys or any(key.ondelete != "CASCADE" for key in keys):
                problems.append(f"{table.name}.{column.name}")
    assert not problems, f"переживут удаление человека: {problems}"


# --- Что уходит вместе с человеком -----------------------------------------

def test_the_diary_and_the_steps_go_away_with_the_person():
    async def scenario():
        async with db() as session:
            session.add(Meal(user_id=1, meal_type=MealTypeEnum.BREAKFAST,
                             name="Овсянка", weight_g=200, calories=250,
                             protein_g=8, fat_g=5, carbs_g=40,
                             source=MealSourceEnum.TEXT))
            await session.commit()
            await step_service.record(session, 1, 9000)

            assert await deletion.purge(session, 1) is True

            assert (await session.execute(select(Meal))).first() is None
            assert (await session.execute(select(StepLog))).first() is None
    run(scenario)


def test_the_other_side_of_a_friendship_does_not_survive():
    """Дружба хранится двумя строками, и обратную каскад не заберёт."""
    async def scenario():
        async with db() as session:
            await friends.connect(session, 1, 2)
            assert await friends.count(session, 2) == 1

            await deletion.purge(session, 1)

            assert await deletion.orphan_friendships(session) == 0
            assert await friends.count(session, 2) == 0
    run(scenario)


def test_leaving_the_team_empty_removes_it_with_its_invite_code():
    async def scenario():
        async with db() as session:
            _, team = await teams.create(session, 1, "Лисы")
            code = team.code

            await deletion.purge(session, 1)

            assert (await session.execute(select(Team))).first() is None
            assert (await teams.join(session, 2, code))[0] == "no_team"
    run(scenario)


def test_the_team_survives_its_creator_and_gets_a_new_owner():
    """Иначе команда остаётся без хозяина и её нельзя даже переименовать."""
    async def scenario():
        async with db() as session:
            _, team = await teams.create(session, 1, "Лисы")
            await teams.join(session, 2, team.code)
            await teams.join(session, 3, team.code)

            await deletion.purge(session, 1)

            alive = await teams.my_team(session, 2)
            assert alive is not None and alive.name == "Лисы"
            assert alive.owner_id == 2
            assert await teams.rename(session, 2, "Волки") is True
    run(scenario)


def test_the_owner_who_simply_leaves_also_hands_the_team_over():
    async def scenario():
        async with db() as session:
            _, team = await teams.create(session, 1, "Лисы")
            await teams.join(session, 2, team.code)

            await teams.leave(session, 1)

            assert (await teams.my_team(session, 2)).owner_id == 2
    run(scenario)


def test_the_deleted_person_disappears_from_the_team_table():
    """Удалилась, а имя всё ещё в таблице — это и есть «данные не удалены»."""
    async def scenario():
        async with db() as session:
            _, team = await teams.create(session, 1, "Лисы")
            await teams.join(session, 2, team.code)
            await step_service.record(session, 1, 9000)
            await step_service.record(session, 2, 5000)

            await deletion.purge(session, 1)

            board = await teams.board(session, 2)
            assert [row.user_id for row in board.rows] == [2]
    run(scenario)


def test_deleting_someone_who_is_already_gone_is_not_an_error():
    async def scenario():
        async with db() as session:
            assert await deletion.purge(session, 999) is False
    run(scenario)


def test_the_handler_uses_the_full_cleanup_not_a_bare_delete():
    """`session.delete(user)` в обработчике снова оставил бы хвосты."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "handlers" /
              "legal.py").read_text(encoding="utf-8")
    assert "deletion.purge" in source
    assert "session.delete(user)" not in source
