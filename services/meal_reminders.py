"""Напоминание, если за день ещё не занесён ни один приём пищи.

По просьбе тестировщиц: тот же принцип, что и для добавок в services/reminders.py —
раз в минуту сверяем местное время человека с фиксированным часом и, если
дневник за сегодня пуст, напоминаем один раз.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Meal, User
from utils.timeframe import day_bounds, to_local

# Вечер, но не ночь: ещё есть время поесть и записать, а не только
# отчитаться перед сном.
REMINDER_TIME = time(20, 0)


@dataclass(frozen=True)
class MealNudge:
    user_id: int


async def users_without_meals_today(
    session: AsyncSession, *, now_utc: datetime | None = None
) -> list[MealNudge]:
    """Кому сейчас (по их местному времени) пора напомнить про дневник."""
    moment = now_utc or datetime.now(timezone.utc)

    users = (
        await session.execute(
            select(User).where(
                User.onboarding_completed.is_(True), User.reminders_enabled.is_(True)
            )
        )
    ).scalars().all()

    nudges: list[MealNudge] = []
    for user in users:
        local_now = to_local(moment, user.timezone)
        if (local_now.hour, local_now.minute) != (REMINDER_TIME.hour, REMINDER_TIME.minute):
            continue

        start, end = day_bounds(user.timezone, day=local_now.date())
        logged = (
            await session.execute(
                select(Meal.id)
                .where(Meal.user_id == user.id, Meal.logged_at >= start, Meal.logged_at < end)
                .limit(1)
            )
        ).first()
        if logged is None:
            nudges.append(MealNudge(user_id=user.id))

    return nudges


__all__ = ["MealNudge", "REMINDER_TIME", "users_without_meals_today"]
