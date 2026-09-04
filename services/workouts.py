"""Тренировки: подбор программы, запись выполнения, история."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LevelEnum, LocationEnum, Workout, WorkoutLog, WorkoutTypeEnum
from seed.workout_programs import PROGRAMS
from utils.met import (
    calories_burned,
    strength_exercise_calories,
    strength_exercise_minutes,
    timed_exercise_minutes,
)
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds, today_in

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgramInfo:
    code: str
    title: str
    subtitle: str
    location: str
    level: str
    exercise_count: int


def available_programs(*, location: str | None = None, level: str | None = None) -> list[ProgramInfo]:
    """Программы, подходящие под место и уровень."""
    result = []
    for code, program in PROGRAMS.items():
        if location and program["location"] != location:
            continue
        if level and program["level"] != level:
            continue
        result.append(
            ProgramInfo(
                code=code,
                title=program["title"],
                subtitle=program["subtitle"],
                location=program["location"],
                level=program["level"],
                exercise_count=len(program["exercises"]),
            )
        )
    return result


async def program_exercises(session: AsyncSession, program_code: str) -> list[Workout]:
    rows = (
        (
            await session.execute(
                select(Workout)
                .where(Workout.program_code == program_code)
                .order_by(Workout.position)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def exercise_calories(workout: Workout, weight_kg: float, *, minutes: float | None = None) -> float:
    """Расход на одно упражнение: у кардио — по минутам, у силовых — по подходам."""
    if workout.workout_type == WorkoutTypeEnum.CARDIO or minutes is not None:
        duration = minutes if minutes is not None else (workout.duration_minutes or 0)
        return calories_burned(met=workout.met_value, weight_kg=weight_kg, minutes=duration)

    # У силового упражнения «на время» (планка) длительность задана в секундах.
    if workout.duration_minutes:
        return calories_burned(
            met=workout.met_value, weight_kg=weight_kg, minutes=exercise_minutes(workout)
        )

    return strength_exercise_calories(
        met=workout.met_value,
        weight_kg=weight_kg,
        sets=workout.sets or 0,
        reps=workout.reps or 0,
        rest_seconds=workout.rest_seconds or 0,
    )


def exercise_minutes(workout: Workout) -> float:
    if workout.workout_type == WorkoutTypeEnum.CARDIO:
        return float(workout.duration_minutes or 0)
    if workout.duration_minutes:
        return timed_exercise_minutes(
            sets=workout.sets or 0,
            seconds_per_set=int(workout.duration_minutes),
            rest_seconds=workout.rest_seconds or 0,
        )
    return strength_exercise_minutes(
        sets=workout.sets or 0, reps=workout.reps or 0, rest_seconds=workout.rest_seconds or 0
    )


async def log_session(
    session: AsyncSession,
    *,
    user_id: int,
    weight_kg: float,
    exercise_ids: list[int],
    minutes: float | None = None,
) -> tuple[int, float, float]:
    """Записать выполненные упражнения.

    Возвращает (сколько записано, всего минут, всего калорий).
    """
    if not exercise_ids:
        return 0, 0.0, 0.0

    workouts = (
        (await session.execute(select(Workout).where(Workout.id.in_(exercise_ids))))
        .scalars()
        .all()
    )

    total_minutes = 0.0
    total_calories = 0.0
    for workout in workouts:
        # Минуты задаются снаружи только для кардио — там их вводит пользователь.
        own_minutes = minutes if workout.workout_type == WorkoutTypeEnum.CARDIO else None
        burned = exercise_calories(workout, weight_kg, minutes=own_minutes)
        spent = own_minutes if own_minutes is not None else exercise_minutes(workout)

        session.add(
            WorkoutLog(
                user_id=user_id,
                workout_id=workout.id,
                sets_done=workout.sets,
                reps_done=workout.reps,
                duration_minutes=round(spent, 1),
                calories_burned=round(burned, 1),
            )
        )
        total_minutes += spent
        total_calories += burned

    await session.commit()
    return len(workouts), round(total_minutes, 1), round(total_calories)


async def recent_sessions(
    session: AsyncSession, user_id: int, *, days: int = 30, timezone_name: str = DEFAULT_TIMEZONE
) -> list[WorkoutLog]:
    start, _ = day_bounds(timezone_name, day=today_in(timezone_name) - timedelta(days=days - 1))
    rows = (
        (
            await session.execute(
                select(WorkoutLog)
                .where(WorkoutLog.user_id == user_id, WorkoutLog.completed_at >= start)
                .order_by(WorkoutLog.completed_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def week_summary(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> dict:
    """Сколько тренировок и калорий за последние 7 дней."""
    logs = await recent_sessions(session, user_id, days=7, timezone_name=timezone_name)

    from utils.timeframe import get_zone

    zone = get_zone(timezone_name)
    days = {log.completed_at.astimezone(zone).date() for log in logs}
    return {
        "workouts": len(days),
        "exercises": len(logs),
        "calories": round(sum(log.calories_burned or 0 for log in logs)),
        "minutes": round(sum(log.duration_minutes or 0 for log in logs)),
    }
