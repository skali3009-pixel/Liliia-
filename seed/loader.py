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
    """Добавить недостающие программы. Возвращает число новых упражнений."""
    existing = set(
        (await session.execute(select(Workout.program_code).distinct())).scalars().all()
    )
    added = 0

    for code, program in PROGRAMS.items():
        if code in existing:
            continue
        for position, row in enumerate(program["exercises"]):
            name, muscle, sets, reps, rest, met = row[:6]
            seconds_per_set = row[6] if len(row) > 6 else None
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

    if CARDIO_CODE not in existing:
        for position, (name, minutes, met) in enumerate(CARDIO):
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

    if added:
        await session.commit()
        logger.info("Добавлено упражнений в библиотеку: %s", added)
    return added
