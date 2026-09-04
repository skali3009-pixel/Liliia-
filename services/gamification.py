"""Игра поверх дневника: задания дня, опыт, уровень, стрик и награды.

Ничего не нужно отмечать руками — всё считается по тем же записям, что уже
есть в базе. Итог дня сохраняется в day_stats: сегодняшняя строка
пересчитывается при каждом открытии приложения, прошедшие остаются как есть.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Achievement, BodyMeasurement, DayStat, Meal, User, WorkoutLog
from utils.game import (
    ACHIEVEMENT_BY_CODE,
    ACHIEVEMENTS,
    build_quests,
    crystal_stage,
    day_xp,
    earned_codes,
    level_from_xp,
)
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds, get_zone, today_in

logger = logging.getLogger(__name__)


async def _workouts_today(session: AsyncSession, user_id: int, timezone_name: str) -> int:
    start, end = day_bounds(timezone_name)
    stmt = select(func.count()).select_from(WorkoutLog).where(
        WorkoutLog.user_id == user_id,
        WorkoutLog.completed_at >= start,
        WorkoutLog.completed_at < end,
    )
    return int((await session.execute(stmt)).scalar_one())


async def _workout_days_total(session: AsyncSession, user_id: int, timezone_name: str) -> int:
    """Тренировкой считаем день с занятием, а не каждое упражнение отдельно."""
    stmt = select(WorkoutLog.completed_at).where(WorkoutLog.user_id == user_id)
    zone = get_zone(timezone_name)
    return len({moment.astimezone(zone).date() for moment in (await session.execute(stmt)).scalars()})


async def _days_since_measure(
    session: AsyncSession, user_id: int, timezone_name: str
) -> int | None:
    stmt = (
        select(BodyMeasurement.measured_at)
        .where(BodyMeasurement.user_id == user_id, BodyMeasurement.weight_kg.is_not(None))
        .order_by(BodyMeasurement.measured_at.desc())
        .limit(1)
    )
    last = (await session.execute(stmt)).scalar_one_or_none()
    if last is None:
        return None
    return (today_in(timezone_name) - last.astimezone(get_zone(timezone_name)).date()).days


async def _losses(session: AsyncSession, user: User) -> tuple[float, float]:
    """Сколько сброшено килограммов и сантиметров талии от первого замера."""
    async def edges(field):
        column = getattr(BodyMeasurement, field)
        stmt = (
            select(column)
            .where(BodyMeasurement.user_id == user.id, column.is_not(None))
            .order_by(BodyMeasurement.measured_at)
        )
        values = list((await session.execute(stmt)).scalars())
        return (values[0], values[-1]) if values else (None, None)

    first_weight, last_weight = await edges("weight_kg")
    first_waist, last_waist = await edges("waist_cm")

    weight_lost = (first_weight - last_weight) if first_weight and last_weight else 0.0
    waist_lost = (first_waist - last_waist) if first_waist and last_waist else 0.0
    return max(weight_lost, 0.0), max(waist_lost, 0.0)


async def _upsert_day(
    session: AsyncSession, user_id: int, day: date, xp: int, codes: list[str]
) -> list[str]:
    """Сохранить итог дня. Возвращает задания, закрытые именно сейчас."""
    stmt = select(DayStat).where(DayStat.user_id == user_id, DayStat.day == day)
    row = (await session.execute(stmt)).scalar_one_or_none()

    known = set(row.quests_done.split(",")) if row and row.quests_done else set()
    fresh = [code for code in codes if code not in known]

    if row is None:
        row = DayStat(user_id=user_id, day=day, xp=xp, quests_done=",".join(codes))
        session.add(row)
    else:
        row.xp = xp
        row.quests_done = ",".join(codes)

    return fresh


async def _streak(session: AsyncSession, user_id: int, today: date) -> int:
    """Дни подряд, в которые закрыто хоть одно задание."""
    stmt = select(DayStat.day).where(DayStat.user_id == user_id, DayStat.xp > 0)
    active = set((await session.execute(stmt)).scalars())
    if not active:
        return 0

    # Сегодня ещё может быть пустым — тогда считаем от вчера, чтобы стрик не
    # обнулялся каждое утро до первого действия.
    cursor = today if today in active else today - timedelta(days=1)
    streak = 0
    while cursor in active:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


async def _sync_achievements(
    session: AsyncSession, user: User, *, streak: int, level: int, timezone_name: str
) -> tuple[list[dict], set[str]]:
    """Выдать заслуженные награды. Возвращает новые и все полученные коды."""
    meals_total = int(
        (await session.execute(
            select(func.count()).select_from(Meal).where(Meal.user_id == user.id)
        )).scalar_one()
    )
    workouts_total = await _workout_days_total(session, user.id, timezone_name)
    weight_lost, waist_lost = await _losses(session, user)

    deserved = earned_codes(
        meals_total=meals_total,
        streak=streak,
        level=level,
        weight_lost_kg=weight_lost,
        waist_lost_cm=waist_lost,
        workouts_total=workouts_total,
    )

    owned = set(
        (await session.execute(
            select(Achievement.code).where(Achievement.user_id == user.id)
        )).scalars()
    )

    fresh = []
    for code in deserved - owned:
        item = ACHIEVEMENT_BY_CODE[code]
        session.add(Achievement(user_id=user.id, code=code, title=item.title))
        fresh.append({"code": code, "title": item.title, "icon": item.icon})

    return fresh, deserved | owned


async def sync_today(
    session: AsyncSession,
    user: User,
    *,
    meals_count: int,
    calories: float,
    fiber_g: float,
    water_ml: float,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict:
    """Пересчитать игровое состояние на сегодня и сохранить его."""
    today = today_in(timezone_name)

    quests = build_quests(
        meals_count=meals_count,
        calories=calories,
        calories_norm=user.daily_calories or 0,
        water_ml=water_ml,
        water_norm_ml=user.daily_water_ml or 0,
        fiber_g=fiber_g,
        fiber_norm_g=user.daily_fiber_g or 0,
        workouts_today=await _workouts_today(session, user.id, timezone_name),
        days_since_measure=await _days_since_measure(session, user.id, timezone_name),
    )

    done_codes = [quest.code for quest in quests if quest.done]
    fresh_quests = await _upsert_day(session, user.id, today, day_xp(quests), done_codes)
    await session.flush()

    total_xp = int(
        (await session.execute(
            select(func.coalesce(func.sum(DayStat.xp), 0)).where(DayStat.user_id == user.id)
        )).scalar_one()
    )
    level = level_from_xp(total_xp)
    streak = await _streak(session, user.id, today)

    fresh_awards, owned = await _sync_achievements(
        session, user, streak=streak, level=level.number, timezone_name=timezone_name
    )
    await session.commit()

    return {
        "xp": total_xp,
        "level": level.number,
        "xp_in_level": level.xp_in_level,
        "xp_to_next": level.xp_to_next,
        "level_share": round(level.share, 3),
        "crystal": crystal_stage(level.number),
        "streak": streak,
        "xp_today": day_xp(quests),
        "quests": [quest.to_dict() for quest in quests],
        "quests_done": len(done_codes),
        "quests_total": len(quests),
        "just_completed": fresh_quests,
        "new_awards": fresh_awards,
        "awards": [
            {
                "code": item.code,
                "title": item.title,
                "icon": item.icon,
                "goal": item.goal,
                "earned": item.code in owned,
            }
            for item in ACHIEVEMENTS
        ],
    }


async def awards_summary(session: AsyncSession, user_id: int) -> list[dict]:
    """Все награды с отметкой, какие уже получены — для экрана прогресса."""
    owned = set(
        (await session.execute(
            select(Achievement.code).where(Achievement.user_id == user_id)
        )).scalars()
    )
    return [
        {
            "code": item.code,
            "title": item.title,
            "icon": item.icon,
            "goal": item.goal,
            "earned": item.code in owned,
        }
        for item in ACHIEVEMENTS
    ]
