"""Мои заготовки: что наготовлено, сколько ещё хранится и что пора съесть.

Справочник заготовок отвечает на вопрос «сколько хранится борщ». Здесь —
на вопрос «что у меня в холодильнике и что портится сегодня». Без второго
первое остаётся справкой, а не помощью.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Prep, UserPrep
from utils.timeframe import DEFAULT_TIMEZONE, today_in

# Сколько дней осталось, чтобы считать «пора съесть».
SOON_DAYS = 1

# Если срок не написан вовсе — считаем по самому осторожному сроку из её же
# справочника. Лучше напомнить раньше, чем позже.
DEFAULT_FRIDGE_DAYS = 3


def shelf_days(text: str | None) -> int:
    """Сколько дней хранится, по её же формулировке.

    В справочнике сроки написаны словами: «3 дня», «3–4 дня», «4–5 дней;
    лучше в стекле». Берём нижнюю границу: из «три-четыре дня» безопаснее
    услышать три.
    """
    if not text:
        return DEFAULT_FRIDGE_DAYS
    found = re.search(r"\d+", text)
    return int(found.group()) if found else DEFAULT_FRIDGE_DAYS


@dataclass(frozen=True)
class MyPrep:
    """Заготовка в холодильнике конкретного человека."""

    code: str
    name: str
    made_on: date
    days_left: int

    @property
    def expiring(self) -> bool:
        return self.days_left <= SOON_DAYS

    @property
    def gone(self) -> bool:
        return self.days_left < 0

    @property
    def hint(self) -> str:
        if self.gone:
            return "Срок вышел — лучше не рисковать"
        if self.days_left == 0:
            return "Лучше доесть сегодня"
        if self.days_left == 1:
            return "Остался день"
        return f"Ещё {self.days_left} дн."

    def to_dict(self) -> dict:
        return {"code": self.code, "name": self.name,
                "made_on": self.made_on.isoformat(), "days_left": self.days_left,
                "expiring": self.expiring, "gone": self.gone, "hint": self.hint}


async def mark_made(session: AsyncSession, user_id: int, prep_code: str, *,
                    timezone_name: str = DEFAULT_TIMEZONE) -> None:
    """Отметить, что заготовка приготовлена сегодня.

    Повторная отметка обновляет дату: люди готовят одно и то же не раз.
    """
    today = today_in(timezone_name)
    row = (await session.execute(
        select(UserPrep).where(UserPrep.user_id == user_id,
                               UserPrep.prep_code == prep_code)
    )).scalar_one_or_none()

    if row is None:
        session.add(UserPrep(user_id=user_id, prep_code=prep_code, made_on=today))
    else:
        row.made_on = today
    await session.commit()


async def forget(session: AsyncSession, user_id: int, prep_code: str) -> None:
    """Съели или выбросили — из холодильника убрать."""
    await session.execute(delete(UserPrep).where(
        UserPrep.user_id == user_id, UserPrep.prep_code == prep_code))
    await session.commit()


async def mine(session: AsyncSession, user_id: int, *,
               timezone_name: str = DEFAULT_TIMEZONE) -> list[MyPrep]:
    """Что сейчас в холодильнике. Просроченное показываем, но помечаем."""
    rows = (await session.execute(
        select(UserPrep).where(UserPrep.user_id == user_id)
    )).scalars().all()
    if not rows:
        return []

    catalogue = {p.code: p for p in (await session.execute(select(Prep))).scalars()}
    today = today_in(timezone_name)

    out = []
    for row in rows:
        prep = catalogue.get(row.prep_code)
        if prep is None:
            continue
        keeps = shelf_days(prep.fridge_days)
        left = (row.made_on + timedelta(days=keeps) - today).days
        out.append(MyPrep(code=row.prep_code,
                          name=prep.name, made_on=row.made_on, days_left=left))

    out.sort(key=lambda item: item.days_left)
    return out


async def expiring_names(session: AsyncSession, user_id: int, *,
                         timezone_name: str = DEFAULT_TIMEZONE) -> tuple[str, ...]:
    """Что стоит съесть сегодня — для карточки «Твой ход»."""
    return tuple(item.name for item in
                 await mine(session, user_id, timezone_name=timezone_name)
                 if item.expiring and not item.gone)


async def my_codes(session: AsyncSession, user_id: int) -> set[str]:
    """Коды заготовок, которые у человека есть, — для подбора блюд."""
    rows = (await session.execute(
        select(UserPrep.prep_code).where(UserPrep.user_id == user_id)
    )).scalars().all()
    return set(rows)


__all__ = ["DEFAULT_FRIDGE_DAYS", "MyPrep", "SOON_DAYS", "expiring_names",
           "forget", "mark_made", "mine", "my_codes", "shelf_days"]
