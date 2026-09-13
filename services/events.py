"""Событие дня и находка: состояние и начисление.

Правила начисления здесь одни и те же для обоих: один раз в день, только
за уже закрытые задания и никогда — задним числом за то, чего не было.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DayStat
from utils.events import Event, event_for, surprise_for
from utils.timeframe import DEFAULT_TIMEZONE, today_in


@dataclass(frozen=True)
class EventState:
    """Событие вместе с тем, насколько человек к нему близок."""

    event: Event
    done: int
    rewarded: bool

    @property
    def complete(self) -> bool:
        return self.done >= self.event.target

    @property
    def share(self) -> float:
        return min(self.done / max(self.event.target, 1), 1.0)

    @property
    def hint(self) -> str:
        if self.rewarded:
            return f"Открыто. +{self.event.crystals} 💎"
        if self.complete:
            return "Готово — загляни ещё раз"
        left = self.event.target - self.done
        return f"Осталось закрыть {left} из {self.event.target}"

    def to_dict(self) -> dict:
        return {**self.event.to_dict(), "done": self.done,
                "complete": self.complete, "rewarded": self.rewarded,
                "share": round(self.share, 3), "hint": self.hint}


async def _today_row(session: AsyncSession, user_id: int, day) -> DayStat | None:
    return (await session.execute(
        select(DayStat).where(DayStat.user_id == user_id, DayStat.day == day)
    )).scalar_one_or_none()


async def _award(session: AsyncSession, row: DayStat, code: str, crystals: int) -> bool:
    """Начислить бонус, если за это сегодня ещё не платили."""
    given = [part for part in (row.bonus_codes or "").split(",") if part]
    if code in given:
        return False
    given.append(code)
    row.bonus_codes = ",".join(given)
    row.bonus = (row.bonus or 0) + crystals
    await session.commit()
    return True


async def state(session: AsyncSession, user_id: int, quests_done: int, *,
                timezone_name: str = DEFAULT_TIMEZONE) -> EventState | None:
    """Событие сегодняшнего дня. Заодно начисляет награду, когда пора."""
    day = today_in(timezone_name)
    event = event_for(user_id, day.isoformat())
    if event is None:
        return None

    row = await _today_row(session, user_id, day)
    if row is None:
        return EventState(event, quests_done, rewarded=False)

    given = [part for part in (row.bonus_codes or "").split(",") if part]
    rewarded = "event" in given
    if quests_done >= event.target and not rewarded:
        rewarded = await _award(session, row, "event", event.crystals) or rewarded

    return EventState(event, quests_done, rewarded=rewarded)


async def surprise(session: AsyncSession, user_id: int, *, closed_now: bool,
                   timezone_name: str = DEFAULT_TIMEZONE) -> int:
    """Находка после закрытого задания. Возвращает начисленные кристаллы.

    Сама по себе она не появляется: сначала человек что-то сделал, и только
    потом мир может его порадовать.
    """
    if not closed_now:
        return 0

    day = today_in(timezone_name)
    crystals = surprise_for(user_id, day.isoformat())
    if not crystals:
        return 0

    row = await _today_row(session, user_id, day)
    if row is None:
        return 0
    return crystals if await _award(session, row, "surprise", crystals) else 0


__all__ = ["EventState", "state", "surprise"]
