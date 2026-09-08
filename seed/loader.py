"""Заливка библиотеки упражнений в базу.

Вызывается при старте бота. Повторный запуск ничего не дублирует: если
упражнения программы уже есть, она пропускается.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LevelEnum, LocationEnum, Workout, WorkoutTypeEnum
from seed.workout_programs import CARDIO, PROGRAMS, demo_url

logger = logging.getLogger(__name__)

CARDIO_CODE = "cardio"


async def seed_workouts(session: AsyncSession) -> int:
    """Досоздать недостающее и перенести переехавшие программы.

    Раньше загрузчик просто пропускал всё, что уже есть в базе. Из-за этого
    любое изменение справочника доезжало только до новых установок: йога,
    переехавшая из «Тела» в «Спокойное», на работающем сервере осталась бы
    там же, где лежала, а новые занятия в списке кардио не появились бы
    вовсе — код программы-то на месте.

    Поэтому теперь: недостающее добавляем, переехавшее обновляем, и ничего
    никогда не удаляем. На упражнения ссылаются записи о тренировках, и
    удалённая строка унесла бы с собой чужой дневник.
    """
    rows = (await session.execute(select(Workout))).scalars().all()
    by_program: dict[str, list[Workout]] = {}
    for row in rows:
        by_program.setdefault(row.program_code or "", []).append(row)

    added = 0

    for code, program in PROGRAMS.items():
        known = {row.name: row for row in by_program.get(code, [])}

        for row in known.values():
            row.category = program["category"]
            row.style = program.get("style")

        for position, item in enumerate(program["exercises"]):
            name, muscle, sets, reps, rest, met = item[:6]
            seconds_per_set = item[6] if len(item) > 6 else None
            if name in known:
                known[name].position = position
                continue
            session.add(
                Workout(
                    name=name,
                    workout_type=WorkoutTypeEnum.STRENGTH,
                    location=LocationEnum(program["location"]),
                    level=LevelEnum(program["level"]),
                    program_code=code,
                    category=program["category"],
                    style=program.get("style"),
                    position=position,
                    muscle_group=muscle,
                    # Для упражнений на время храним длительность подхода.
                    duration_minutes=seconds_per_set,
                    sets=sets,
                    reps=reps,
                    rest_seconds=rest,
                    met_value=met,
                    demo_url=demo_url(name),
                )
            )
            added += 1

    known_cardio = {row.name: row for row in by_program.get(CARDIO_CODE, [])}
    for position, (name, minutes, met) in enumerate(CARDIO):
        if name in known_cardio:
            known_cardio[name].position = position
            continue
        session.add(
            Workout(
                name=name,
                workout_type=WorkoutTypeEnum.CARDIO,
                location=LocationEnum.HOME,
                level=LevelEnum.BEGINNER,
                program_code=CARDIO_CODE,
                category="body",
                style="cardio",
                position=position,
                duration_minutes=minutes,
                met_value=met,
                demo_url=demo_url(name),
            )
        )
        added += 1

    # Переносы категорий надо сохранить, даже когда ничего не добавилось.
    await session.commit()

    if added:
        logger.info("Добавлено упражнений в библиотеку: %s", added)
    return added
