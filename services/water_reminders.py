"""Напоминание про воду — одно за день и только тем, кто отстаёт.

Пить воду забывают буквально все, и это единственное напоминание, которое в
таких приложениях реально работает. Но оно же быстрее всего надоедает,
поэтому здесь жёсткие рамки: один раз в день, в середине дня, и только если
к этому часу выпито меньше половины нормы. Кто пьёт — тот бота не слышит.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, WaterLog
from utils.timeframe import day_bounds, to_local

# Середина дня: успеть допить до вечера ещё реально.
REMINDER_TIME = time(16, 0)

# Ниже этой доли нормы напоминание уместно, выше — человек и так пьёт.
BEHIND_SHARE = 0.5

# Если норма не рассчитана, берём обычные полтора литра.
FALLBACK_NORM_ML = 1500


@dataclass(frozen=True)
class WaterNudge:
    user_id: int
    drunk_ml: int
    norm_ml: int

    @property
    def left_ml(self) -> int:
        return max(self.norm_ml - self.drunk_ml, 0)


async def users_behind_on_water(
    session: AsyncSession, *, now_utc: datetime | None = None
) -> list[WaterNudge]:
    """Кому сейчас (по их местному времени) стоит напомнить про воду."""
    moment = now_utc or datetime.now(timezone.utc)

    users = (
        await session.execute(
            select(User).where(
                User.onboarding_completed.is_(True), User.reminders_enabled.is_(True)
            )
        )
    ).scalars().all()

    nudges: list[WaterNudge] = []
    for user in users:
        local_now = to_local(moment, user.timezone)
        if (local_now.hour, local_now.minute) != (REMINDER_TIME.hour, REMINDER_TIME.minute):
            continue

        start, end = day_bounds(user.timezone, day=local_now.date())
        amounts = (
            await session.execute(
                select(WaterLog.amount_ml).where(
                    WaterLog.user_id == user.id,
                    WaterLog.logged_at >= start,
                    WaterLog.logged_at < end,
                )
            )
        ).scalars().all()

        drunk = sum(int(value) for value in amounts)
        norm = user.daily_water_ml or FALLBACK_NORM_ML
        if drunk < norm * BEHIND_SHARE:
            nudges.append(WaterNudge(user_id=user.id, drunk_ml=drunk, norm_ml=norm))

    return nudges


def render(nudge: WaterNudge) -> str:
    if nudge.drunk_ml == 0:
        return (
            "💧 Воды за сегодня пока не отмечено.\n\n"
            f"Норма — {nudge.norm_ml} мл. Начать можно со стакана прямо сейчас."
        )
    return (
        f"💧 Воды за сегодня: {nudge.drunk_ml} из {nudge.norm_ml} мл.\n\n"
        f"До вечера осталось {nudge.left_ml} мл — это несколько стаканов."
    )


__all__ = ["BEHIND_SHARE", "REMINDER_TIME", "WaterNudge", "render", "users_behind_on_water"]
