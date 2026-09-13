"""Чем в чате пользуются, а чем нет.

До этого ответ был один: «кажется, жмут только еду и воду». Кажется — не
основание убирать кнопку: убрав нужную, узнаёшь об этом от рассерженного
человека, а не из отчёта.

Считаем сводкой: человек, кнопка, день. Так видно и сколько нажатий, и
скольким людям кнопка вообще нужна — а это разные вещи. Кнопку, которую
один человек жмёт двадцать раз в день, а остальные не трогают, убирать
нельзя, но и оставлять на видном месте незачем.

Счёт временный, на время испытаний. Поэтому отчёт сам напоминает, что он
включён, и говорит, как его выключить: забытый счётчик тихо растит
таблицу и остаётся в коде навсегда.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ButtonPress
from utils.timeframe import DEFAULT_TIMEZONE, today_in

logger = logging.getLogger(__name__)

# Сколько дней смотрим в отчёте.
WINDOW_DAYS = 30


def label(text: str) -> str:
    """Подпись кнопки без эмодзи: «🐆 Мой ход» → «Мой ход»."""
    return " ".join(part for part in text.split() if part.isalpha() or "-" in part) \
        or text.strip()


async def note(session: AsyncSession, user_id: int, button: str, *,
               timezone_name: str = DEFAULT_TIMEZONE,
               now_utc: datetime | None = None) -> None:
    """Отметить нажатие. Одна строка на человека, кнопку и день."""
    day = today_in(timezone_name, now=now_utc)
    name = label(button)

    row = (await session.execute(
        select(ButtonPress).where(ButtonPress.user_id == user_id,
                                  ButtonPress.button == name,
                                  ButtonPress.day == day)
    )).scalar_one_or_none()

    if row is None:
        session.add(ButtonPress(user_id=user_id, button=name, day=day, count=1))
    else:
        row.count += 1
    await session.commit()


@dataclass(frozen=True)
class Use:
    """Одна кнопка: сколько нажатий и скольким людям она понадобилась."""

    button: str
    presses: int
    people: int


async def usage(session: AsyncSession, *, days: int = WINDOW_DAYS,
                now_utc: datetime | None = None) -> list[Use]:
    """Кнопки по убыванию числа людей, которым они пригодились."""
    moment = now_utc or datetime.now(timezone.utc)
    edge = (moment - timedelta(days=days)).date()
    rows = (await session.execute(
        select(ButtonPress.button, func.sum(ButtonPress.count),
               func.count(func.distinct(ButtonPress.user_id)))
        .where(ButtonPress.day >= edge)
        .group_by(ButtonPress.button)
    )).all()
    out = [Use(button=name, presses=int(presses or 0), people=int(people or 0))
           for name, presses, people in rows]
    return sorted(out, key=lambda item: (-item.people, -item.presses))


async def counting_since(session: AsyncSession) -> date | None:
    """С какого дня считаем. Нужно отчёту, чтобы напомнить о себе."""
    return (await session.execute(select(func.min(ButtonPress.day)))).scalar_one_or_none()


__all__ = ["Use", "WINDOW_DAYS", "counting_since", "label", "note", "usage"]
