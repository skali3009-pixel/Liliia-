"""Витамины и лекарства: что положено сегодня и отметки о приёме."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ScheduleTypeEnum, Supplement, SupplementLog
from utils.schedules import describe, is_due
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds, today_in


@dataclass(frozen=True)
class DueSupplement:
    """Препарат, который нужно принять сегодня, и отметка о приёме."""

    supplement: Supplement
    taken: bool
    skipped: bool

    @property
    def schedule_label(self) -> str:
        return describe(
            schedule_type=self.supplement.schedule_type,
            weekdays=self.supplement.weekdays,
            interval_days=self.supplement.interval_days,
        )


def user_today(timezone_name: str) -> date:
    """Сегодняшняя дата в часовом поясе пользователя."""
    return today_in(timezone_name)


async def list_due_today(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> list[DueSupplement]:
    """Препараты на сегодня — с пометкой, приняты они уже или нет."""
    today = user_today(timezone_name)
    day_start, day_end = day_bounds(timezone_name, day=today)

    supplements = (
        (
            await session.execute(
                select(Supplement).where(
                    Supplement.user_id == user_id, Supplement.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )

    logs = (
        (
            await session.execute(
                select(SupplementLog).where(
                    SupplementLog.user_id == user_id,
                    SupplementLog.logged_at >= day_start,
                    SupplementLog.logged_at < day_end,
                )
            )
        )
        .scalars()
        .all()
    )
    logged = {log.supplement_id: log for log in logs}

    due: list[DueSupplement] = []
    for supplement in supplements:
        started = supplement.created_at.date() if supplement.created_at else today
        if not is_due(
            schedule_type=supplement.schedule_type,
            on_date=today,
            start_date=started,
            weekdays=supplement.weekdays,
            interval_days=supplement.interval_days,
        ):
            continue

        log = logged.get(supplement.id)
        due.append(
            DueSupplement(
                supplement=supplement,
                taken=bool(log and not log.skipped),
                skipped=bool(log and log.skipped),
            )
        )
    return due


async def add_supplement(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
    dose: str | None = None,
    schedule_type: ScheduleTypeEnum = ScheduleTypeEnum.DAILY,
    weekdays: str | None = None,
    interval_days: int | None = None,
    reminder_time: time | None = None,
) -> Supplement:
    supplement = Supplement(
        user_id=user_id,
        name=name.strip()[:120],
        dose=(dose or "").strip()[:60] or None,
        schedule_type=schedule_type,
        weekdays=weekdays,
        interval_days=interval_days,
        reminder_time=reminder_time,
    )
    session.add(supplement)
    await session.commit()
    return supplement


async def mark(
    session: AsyncSession,
    *,
    user_id: int,
    supplement_id: int,
    skipped: bool = False,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> SupplementLog:
    """Отметить приём (или пропуск). Повторная отметка за день перезаписывается.

    Часовой пояс передаётся снаружи: тянуть его через supplement.user нельзя —
    в асинхронной сессии ленивая связь не подгружается.
    """
    supplement = await session.get(Supplement, supplement_id)
    if supplement is None or supplement.user_id != user_id:
        raise ValueError("Препарат не найден")

    day_start, day_end = day_bounds(timezone_name)
    existing = (
        await session.execute(
            select(SupplementLog).where(
                SupplementLog.supplement_id == supplement_id,
                SupplementLog.logged_at >= day_start,
                SupplementLog.logged_at < day_end,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.skipped = skipped
        await session.commit()
        return existing

    log = SupplementLog(user_id=user_id, supplement_id=supplement_id, skipped=skipped)
    session.add(log)
    await session.commit()
    return log
