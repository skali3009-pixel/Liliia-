"""Переименование упражнения на живой базе.

Загрузчик ищет упражнение по названию и никогда ничего не удаляет: на
строки ссылаются записи о тренировках, и удалённая строка унесла бы с
собой чужой дневник. Из-за этого простое переименование в справочнике
означало бы не переименование, а добавление: в программе оказались бы две
карточки — новая и призрак со старым названием, у которого нет ни
техники, ни ролика.

Здесь проверяется, что этого не происходит: строка переживает
переименование целиком, вместе со своим номером и дневником за ней. И что
упражнение, убранное из программы, из базы всё-таки не исчезает.
"""

import asyncio
import contextlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (Base, LevelEnum, LocationEnum, Workout, WorkoutLog,
                    WorkoutTypeEnum)
from seed.loader import RENAMED, RETIRED, seed_workouts
from seed.workout_programs import PROGRAMS


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


# Где эти названия лежали до правок. Класть всё в одну программу нельзя:
# тогда тест сравнивал бы её состав с чужими строками и падал бы не по делу.
ГДЕ_ЛЕЖАЛИ = {
    "Лёгкие круги под глазами безымянным пальцем": "face_massage",
    "Разминание скул подушечками пальцев": "face_massage",
    "Массаж линии челюсти костяшками": "face_massage",
    "Проработка носогубных складок": "face_massage",
    "«Жираф»: вытяжение шеи вверх": "chin_line",
    "Язык к нёбу с наклоном головы": "chin_line",
    "Сопротивление ладонью под подбородком": "chin_line",
    "Произнесение «И — У» с напряжением": "chin_line",
    "Наклон головы назад с движением челюсти": "chin_line",
    "Растяжка передней поверхности шеи": "chin_line",
}


async def старая_база(session):
    """База, залитая до переименований: со старыми названиями."""
    старые = list(RENAMED) + list(RETIRED)
    assert set(старые) == set(ГДЕ_ЛЕЖАЛИ), set(старые) ^ set(ГДЕ_ЛЕЖАЛИ)
    for position, name in enumerate(старые):
        session.add(Workout(
            name=name, workout_type=WorkoutTypeEnum.STRENGTH,
            location=LocationEnum.HOME, level=LevelEnum.BEGINNER,
            program_code=ГДЕ_ЛЕЖАЛИ[name], category="face", position=position,
            sets=2, reps=1, rest_seconds=10, met_value=1.5,
        ))
    await session.commit()
    return старые


def test_the_row_survives_the_rename_with_its_diary():
    """Строка та же — значит, записи о тренировках никуда не делись."""
    async def scenario():
        async with db() as session:
            старые = await старая_база(session)
            было = {row.name: row.id for row in
                    (await session.execute(select(Workout))).scalars().all()}

            # Человек когда-то сделал это упражнение.
            имя = next(iter(RENAMED))
            session.add(WorkoutLog(user_id=1, workout_id=было[имя], duration_minutes=8,
                                   calories_burned=20,
                                   completed_at=datetime.now(timezone.utc)))
            await session.commit()

            await seed_workouts(session)

            стало = {row.id: row.name for row in
                     (await session.execute(select(Workout))).scalars().all()}
            for старое, новое in RENAMED.items():
                assert стало[было[старое]] == новое, старое

            запись = (await session.execute(select(WorkoutLog))).scalars().one()
            assert стало[запись.workout_id] == RENAMED[имя]
            assert len(старые) == len(RENAMED) + len(RETIRED)
    run(scenario)


def test_the_program_does_not_grow_a_ghost_card():
    """Иначе в «Самомассаже» стало бы восемь карточек вместо семи."""
    async def scenario():
        async with db() as session:
            await старая_база(session)
            await seed_workouts(session)

            for код in ("face_massage", "chin_line"):
                строки = (await session.execute(
                    select(Workout).where(Workout.program_code == код)
                )).scalars().all()
                имена = [row.name for row in строки]
                assert sorted(имена) == sorted(
                    item[0] for item in PROGRAMS[код]["exercises"]), (код, имена)
                for старое in RENAMED:
                    assert старое not in имена, (код, старое)
    run(scenario)


def test_the_retired_exercise_leaves_the_catalogue_but_not_the_base():
    """Запись о тренировке, сделанной когда-то по нему, должна остаться правдой."""
    async def scenario():
        async with db() as session:
            await старая_база(session)
            await seed_workouts(session)

            for убранное in RETIRED:
                row = (await session.execute(
                    select(Workout).where(Workout.name == убранное)
                )).scalars().one()
                assert row.program_code is None, убранное
    run(scenario)
