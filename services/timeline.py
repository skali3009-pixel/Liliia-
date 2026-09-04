"""Лента дня: всё, что произошло сегодня, одним списком по времени.

Еда, тренировки, отметки состояния и принятые препараты — это разные
таблицы, но для человека это один поток событий его дня.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Checkin, Meal, SupplementLog, WorkoutLog
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds, get_zone

# Упражнения одной тренировки идут подряд; всё, что записано в пределах этого
# промежутка, считаем одним занятием, а не пятью отдельными событиями.
WORKOUT_GAP = timedelta(minutes=90)


@dataclass(frozen=True)
class Event:
    at: datetime
    kind: str      # meal / workout / state / pill
    icon: str
    title: str
    subtitle: str
    value: str = ""
    # id записи, если событие можно поправить или удалить (пока только еда).
    ref_id: int | None = None

    def to_dict(self, zone) -> dict:
        return {
            "time": self.at.astimezone(zone).strftime("%H:%M"),
            "kind": self.kind,
            "icon": self.icon,
            "title": self.title,
            "subtitle": self.subtitle,
            "value": self.value,
            "id": self.ref_id,
        }


def _state_event(checkin: Checkin) -> Event | None:
    """Отметка состояния — одно событие, даже если сказано несколько вещей."""
    parts = []
    if checkin.mood:
        parts.append(f"настроение: {checkin.mood}")
    if checkin.energy:
        parts.append(f"энергия {checkin.energy}/10")
    if checkin.focus:
        parts.append(f"фокус {checkin.focus}/10")
    if checkin.stress:
        parts.append(f"стресс {checkin.stress}")
    if checkin.sleep_minutes:
        hours, minutes = divmod(checkin.sleep_minutes, 60)
        parts.append(f"сон {hours} ч {minutes:02d} м")
    if not parts:
        return None

    return Event(
        at=checkin.logged_at,
        kind="state",
        icon="🤍",
        title=parts[0].capitalize(),
        subtitle=", ".join(parts[1:]),
    )


def _group_workouts(logs: list[WorkoutLog]) -> list[Event]:
    """Свернуть упражнения в занятия по паузам между записями."""
    events: list[Event] = []
    batch: list[WorkoutLog] = []

    def flush() -> None:
        if not batch:
            return
        calories = round(sum(log.calories_burned or 0 for log in batch))
        minutes = round(sum(log.duration_minutes or 0 for log in batch))
        events.append(
            Event(
                at=batch[0].completed_at,
                kind="workout",
                icon="🏋️",
                title="Тренировка",
                subtitle=f"{len(batch)} упражнений · {minutes} мин",
                value=f"{calories} ккал" if calories else "",
            )
        )

    for log in sorted(logs, key=lambda item: item.completed_at):
        if batch and log.completed_at - batch[-1].completed_at > WORKOUT_GAP:
            flush()
            batch = []
        batch.append(log)
    flush()
    return events


async def day_timeline(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> list[dict]:
    """События сегодняшнего дня по возрастанию времени."""
    start, end = day_bounds(timezone_name)
    zone = get_zone(timezone_name)

    def today(model, column):
        return select(model).where(model.user_id == user_id, column >= start, column < end)

    meals = list((await session.execute(today(Meal, Meal.logged_at))).scalars())
    workouts = list((await session.execute(today(WorkoutLog, WorkoutLog.completed_at))).scalars())
    checkins = list((await session.execute(today(Checkin, Checkin.logged_at))).scalars())
    # Название препарата лежит в связанной таблице — подгружаем сразу,
    # иначе async-сессия упадёт на ленивой загрузке.
    pills = list((await session.execute(
        today(SupplementLog, SupplementLog.logged_at)
        .where(SupplementLog.skipped.is_(False))
        .options(selectinload(SupplementLog.supplement))
    )).scalars())

    events: list[Event] = [
        Event(
            at=meal.logged_at,
            kind="meal",
            icon="🍽️",
            title=meal.name,
            subtitle=f"{round(meal.weight_g)} г · Б {round(meal.protein_g)} "
                     f"Ж {round(meal.fat_g)} У {round(meal.carbs_g)}"
                     + (f" · 🥦 {round(meal.fiber_g or 0)}" if meal.fiber_g else ""),
            value=f"{round(meal.calories)} ккал",
            ref_id=meal.id,
        )
        for meal in meals
    ]
    events += _group_workouts(workouts)
    events += [event for event in map(_state_event, checkins) if event]
    events += [
        Event(
            at=log.logged_at,
            kind="pill",
            icon="💊",
            title=log.supplement.name if log.supplement else "Препарат",
            subtitle="принято",
        )
        for log in pills
    ]

    events.sort(key=lambda event: event.at)
    return [event.to_dict(zone) for event in events]
