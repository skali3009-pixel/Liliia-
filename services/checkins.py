"""Отметки состояния: энергия, фокус, настроение, стресс, сон."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Checkin
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds


@dataclass(frozen=True)
class DayState:
    """Состояние дня: последнее сказанное про каждый показатель.

    Показатели живут отдельно: если утром отмечен сон, а днём — энергия,
    к вечеру видно и то, и другое.
    """

    energy: int | None = None
    focus: int | None = None
    mood: str | None = None
    stress: str | None = None
    sleep_minutes: int | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            value is not None
            for value in (self.energy, self.focus, self.mood, self.stress, self.sleep_minutes)
        )


async def save_checkin(
    session: AsyncSession,
    *,
    user_id: int,
    energy: int | None = None,
    focus: int | None = None,
    mood: str | None = None,
    stress: str | None = None,
    sleep_minutes: int | None = None,
    note: str | None = None,
    logged_at: datetime | None = None,
) -> Checkin:
    # В базу время кладём в UTC: драйверы по-разному обходятся с зоной,
    # а UTC читается одинаково везде.
    if logged_at is not None and logged_at.tzinfo is not None:
        logged_at = logged_at.astimezone(timezone.utc)

    checkin = Checkin(
        user_id=user_id,
        energy=energy,
        focus=focus,
        mood=mood,
        stress=stress,
        sleep_minutes=sleep_minutes,
        note=note,
        **({"logged_at": logged_at} if logged_at else {}),
    )
    session.add(checkin)
    await session.commit()
    return checkin


async def list_today(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> list[Checkin]:
    start, end = day_bounds(timezone_name)
    stmt = (
        select(Checkin)
        .where(Checkin.user_id == user_id, Checkin.logged_at >= start, Checkin.logged_at < end)
        .order_by(Checkin.logged_at, Checkin.id)
    )
    return list((await session.execute(stmt)).scalars().all())


def fold_state(checkins: list[Checkin]) -> DayState:
    """Свернуть отметки дня в одно состояние — по последнему упоминанию."""
    state: dict[str, object] = {}
    for checkin in checkins:
        for key in ("energy", "focus", "mood", "stress", "sleep_minutes"):
            value = getattr(checkin, key)
            if value is not None:
                state[key] = value
    return DayState(**state)  # type: ignore[arg-type]


async def today_state(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> DayState:
    return fold_state(await list_today(session, user_id, timezone_name=timezone_name))
