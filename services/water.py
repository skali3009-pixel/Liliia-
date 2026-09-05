"""Трекер воды: быстрые добавления и итог за день."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import WaterLog
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds

# Быстрые кнопки: привычные объёмы, а не абстрактные миллилитры.
GLASS_ML = 250
BOTTLE_ML = 500
MUG_ML = 350


async def add_water(session: AsyncSession, *, user_id: int, amount_ml: int) -> WaterLog:
    entry = WaterLog(user_id=user_id, amount_ml=amount_ml)
    session.add(entry)
    await session.commit()
    return entry


async def today_total_ml(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> int:
    start, end = day_bounds(timezone_name)
    stmt = select(func.coalesce(func.sum(WaterLog.amount_ml), 0)).where(
        WaterLog.user_id == user_id, WaterLog.logged_at >= start, WaterLog.logged_at < end
    )
    return int((await session.execute(stmt)).scalar_one())


async def undo_last(
    session: AsyncSession, user_id: int, *, timezone_name: str = DEFAULT_TIMEZONE
) -> int:
    """Убрать последнюю запись за сегодня (нажала лишний раз). Вернёт объём."""
    start, end = day_bounds(timezone_name)
    stmt = (
        select(WaterLog)
        .where(WaterLog.user_id == user_id, WaterLog.logged_at >= start, WaterLog.logged_at < end)
        # id как второй ключ: у двух нажатий подряд время может совпасть до
        # секунды, и тогда без него удалилась бы не та запись.
        .order_by(WaterLog.logged_at.desc(), WaterLog.id.desc())
        .limit(1)
    )
    entry = (await session.execute(stmt)).scalar_one_or_none()
    if entry is None:
        return 0
    amount = entry.amount_ml
    await session.delete(entry)
    await session.commit()
    return amount
