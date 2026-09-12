"""Напоминания о приёме препаратов.

Раз в минуту проверяем, кому пора: у препарата задано время, сегодня он по
расписанию положен, и отметки о приёме за сегодня ещё нет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Supplement, SupplementLog, User
from utils.schedules import is_due
from utils.timeframe import day_bounds, get_zone, to_local

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reminder:
    user_id: int
    supplement_id: int
    name: str
    dose: str | None


def needs_reminder(
    *,
    reminder_time: time | None,
    local_now: datetime,
    schedule_type,
    start_date: date,
    weekdays: str | None,
    interval_days: int | None,
    already_logged: bool,
) -> bool:
    """Пора ли напоминать об этом препарате прямо сейчас.

    Совпадение проверяем по часу и минуте: задача крутится раз в минуту, так
    что каждое время срабатывает ровно один раз за день.
    """
    if reminder_time is None or already_logged:
        return False
    if (reminder_time.hour, reminder_time.minute) != (local_now.hour, local_now.minute):
        return False
    return is_due(
        schedule_type=schedule_type,
        on_date=local_now.date(),
        start_date=start_date,
        weekdays=weekdays,
        interval_days=interval_days,
    )


async def collect_due_reminders(
    session: AsyncSession, *, now_utc: datetime | None = None
) -> list[Reminder]:
    """Собрать напоминания, которые нужно отправить в эту минуту."""
    moment = now_utc or datetime.now(timezone.utc)

    rows = (
        await session.execute(
            select(Supplement, User)
            .join(User, User.id == Supplement.user_id)
            .where(Supplement.is_active.is_(True), Supplement.reminder_time.is_not(None))
        )
    ).all()

    reminders: list[Reminder] = []
    for supplement, user in rows:
        local_now = to_local(moment, user.timezone)
        start, end = day_bounds(user.timezone, day=local_now.date())

        logged = (
            await session.execute(
                select(SupplementLog.id).where(
                    SupplementLog.supplement_id == supplement.id,
                    SupplementLog.logged_at >= start,
                    SupplementLog.logged_at < end,
                )
            )
        ).first()

        if needs_reminder(
            reminder_time=supplement.reminder_time,
            local_now=local_now,
            schedule_type=supplement.schedule_type,
            start_date=supplement.created_at.date() if supplement.created_at else local_now.date(),
            weekdays=supplement.weekdays,
            interval_days=supplement.interval_days,
            already_logged=logged is not None,
        ):
            reminders.append(
                Reminder(
                    user_id=user.id,
                    supplement_id=supplement.id,
                    name=supplement.name,
                    dose=supplement.dose,
                )
            )
    return reminders
