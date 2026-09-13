"""Совместные недельные цели.

Соревнование «кто больше» в приложении про еду и вес — плохая идея: обогнать
можно голоданием, и приложение само подтолкнёт к этому. Поэтому цель здесь
общая: складываются вклады всех, и выигрывают либо все вместе, либо никто.
Проиграть при этом нельзя — незакрытая цель просто остаётся незакрытой.

Цель считается по кристаллам: их дают за обычные полезные действия и не
дают за голодание и перегрузку. Значит и «стараться ради челленджа» можно
только тем способом, который приложению не вредит.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DayStat, Friendship
from utils.timeframe import DEFAULT_TIMEZONE, today_in

# Сколько кристаллов в неделю ждём с человека. Идеальный день — 105, но
# идеальных недель не бывает: берём заведомо достижимое.
PER_PERSON = 250

# Ниже двух участников это уже не совместная цель, а личная.
MIN_PEOPLE = 2


@dataclass(frozen=True)
class Challenge:
    """Общая цель недели."""

    people: int
    target: int
    done: int
    starts: date
    ends: date
    # Сегодняшнюю дату держим рядом: она уже посчитана в часовом поясе
    # человека, и брать её заново означало бы взять чужой день.
    today: date

    @property
    def complete(self) -> bool:
        return self.done >= self.target

    @property
    def share(self) -> float:
        return min(self.done / max(self.target, 1), 1.0)

    @property
    def days_left(self) -> int:
        return max((self.ends - self.today).days, 0)

    @property
    def hint(self) -> str:
        if self.complete:
            return "Цель недели закрыта. Вместе."
        left = self.target - self.done
        days = self.days_left
        tail = "сегодня последний день" if days == 0 else f"осталось {days} дн."
        return f"Ещё {left} 💎 на всех — {tail}"

    def to_dict(self) -> dict:
        return {"people": self.people, "target": self.target, "done": self.done,
                "complete": self.complete, "share": round(self.share, 3),
                "days_left": self.days_left, "hint": self.hint,
                "starts": self.starts.isoformat(), "ends": self.ends.isoformat()}


def week_bounds(today: date) -> tuple[date, date]:
    """Понедельник и воскресенье той недели, в которой сегодня."""
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


async def current(session: AsyncSession, user_id: int, *,
                  timezone_name: str = DEFAULT_TIMEZONE) -> Challenge | None:
    """Цель недели для человека и его друзей. None — если друзей нет."""
    friend_ids = list((await session.execute(
        select(Friendship.friend_id).where(Friendship.user_id == user_id)
    )).scalars())
    everyone = [user_id, *friend_ids]
    if len(everyone) < MIN_PEOPLE:
        return None

    today = today_in(timezone_name)
    starts, ends = week_bounds(today)

    done = int((await session.execute(
        select(func.coalesce(func.sum(DayStat.xp + DayStat.bonus), 0)).where(
            DayStat.user_id.in_(everyone),
            DayStat.day >= starts,
            DayStat.day <= ends,
        )
    )).scalar_one())

    return Challenge(people=len(everyone), target=PER_PERSON * len(everyone),
                     done=done, starts=starts, ends=ends, today=today)


__all__ = ["Challenge", "MIN_PEOPLE", "PER_PERSON", "current", "week_bounds"]
