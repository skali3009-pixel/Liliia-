"""Состояние мира конкретного человека.

Считает по тому, что уже записано: дни с дневником, дни с закрытой нормой
воды, тренировки, замеры, серия, уровень и сброшенные килограммы. Никаких
новых отметок: мир растёт сам, пока человек живёт своей жизнью.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import BodyMeasurement, DayStat, User
from utils.game import level_from_xp
from utils.timeframe import DEFAULT_TIMEZONE
from utils.world import ZoneState, build, headline, next_unlock


async def _days_with(session: AsyncSession, user_id: int, quest: str) -> int:
    """Сколько дней это задание было закрыто.

    Коды закрытых заданий уже лежат в итоге дня — отдельно считать не нужно.
    """
    return int((await session.execute(
        select(func.count()).select_from(DayStat).where(
            DayStat.user_id == user_id,
            DayStat.quests_done.like(f"%{quest}%"),
        )
    )).scalar_one())


async def facts(session: AsyncSession, user: User, *,
                timezone_name: str = DEFAULT_TIMEZONE) -> dict[str, float]:
    """Числа, которыми двигается мир."""
    from services.gamification import _losses, _streak, _workout_days_total
    from utils.timeframe import today_in

    total_xp = int((await session.execute(
        select(func.coalesce(func.sum(DayStat.xp), 0)).where(DayStat.user_id == user.id)
    )).scalar_one())
    measurements = int((await session.execute(
        select(func.count()).select_from(BodyMeasurement).where(
            BodyMeasurement.user_id == user.id)
    )).scalar_one())
    weight_lost, _ = await _losses(session, user)

    return {
        "diary_days": await _days_with(session, user.id, "meals"),
        "water_days": await _days_with(session, user.id, "water"),
        "workout_days": await _workout_days_total(session, user.id, timezone_name),
        "measurements": measurements,
        "streak": await _streak(session, user.id, today_in(timezone_name)),
        "level": level_from_xp(total_xp).number,
        "weight_lost_kg": round(weight_lost, 1),
    }


async def state(session: AsyncSession, user: User, *,
                timezone_name: str = DEFAULT_TIMEZONE) -> dict:
    """Всё, что нужно экрану «Мой мир», одним ответом."""
    zones: list[ZoneState] = build(await facts(session, user, timezone_name=timezone_name))
    title, subtitle = headline(zones)
    upcoming = next_unlock(zones)

    return {
        "title": title,
        "subtitle": subtitle,
        "zones": [zone.to_dict() for zone in zones],
        "open": sum(1 for zone in zones if zone.open),
        "total": len(zones),
        "next": upcoming.to_dict() if upcoming else None,
    }


__all__ = ["facts", "state"]
