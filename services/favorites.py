"""Что человек ест постоянно — чтобы записать это в одно касание.

Люди едят по кругу два-три десятка блюд. Гонять каждое из них через
распознавание — это несколько секунд ожидания, деньги за запрос и лишний
повод не записать вовсе. Поэтому то, что уже было, предлагается списком:
нажал — записано.

Порция берётся не средняя, а последняя: если человек в прошлый раз поправил
вес, он поправил его осознанно, и повторять надо именно это.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Meal
from utils.timeframe import DEFAULT_TIMEZONE, day_bounds, today_in

# За сколько дней смотрим историю. Меньше — список не успевает набраться,
# больше — в него лезет давно забытое.
LOOKBACK_DAYS = 45

# Сколько показывать. Список должен читаться одним взглядом.
DEFAULT_LIMIT = 8

# Ниже этого блюдо ещё не привычка, а случайность.
MIN_TIMES = 2

_SPACES = re.compile(r"\s+")


def normalize(name: str) -> str:
    """Ключ, по которому «Овсянка», «овсянка » и «Овсянка» — одно блюдо."""
    return _SPACES.sub(" ", (name or "").strip().lower())


def hidden_names(user) -> set[str]:
    """Что человек убрал из списка. Имена уже приведены к одному виду."""
    return {строка for строка in (user.hidden_foods or "").split("\n") if строка}


async def hide(session: AsyncSession, user, name: str) -> bool:
    """Убрать блюдо из списка. False — если нечего убирать.

    Список предлагает то, что человек ел дважды, но «дважды» и «буду есть
    дальше» — разные вещи: съел конфеты на выходных, и они теперь висят между
    овсянкой и кофе. Кнопка «плюс» без обратной кнопки означает, что список
    можно только копить.
    """
    ключ = normalize(name)
    if not ключ:
        return False

    было = hidden_names(user)
    if ключ in было:
        return False

    user.hidden_foods = "\n".join(sorted(было | {ключ}))
    await session.commit()
    return True


async def restore(session: AsyncSession, user) -> int:
    """Вернуть всё скрытое. Возвращает, сколько вернулось.

    Промахнуться по маленькой кнопке легко, а список без возврата врёт
    навсегда — то же правило, что у отметки в женском календаре. Возвращаем
    всё разом: выбирать из скрытого некому, его и не видно.
    """
    сколько = len(hidden_names(user))
    if not сколько:
        return 0
    user.hidden_foods = None
    await session.commit()
    return сколько


@dataclass(frozen=True)
class Favorite:
    """Блюдо из истории, готовое к повторной записи."""

    name: str
    weight_g: float
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float
    times: int

    def to_dict(self) -> dict:
        return asdict(self)


async def frequent_meals(
    session: AsyncSession,
    user_id: int,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    days: int = LOOKBACK_DAYS,
    limit: int = DEFAULT_LIMIT,
    min_times: int = MIN_TIMES,
    hidden: set[str] | None = None,
) -> list[Favorite]:
    """Самое частое из съеденного за последние недели, кроме убранного."""
    start, _ = day_bounds(
        timezone_name, day=today_in(timezone_name) - timedelta(days=days - 1)
    )
    rows = (
        (
            await session.execute(
                select(Meal)
                .where(Meal.user_id == user_id, Meal.logged_at >= start)
                .order_by(Meal.logged_at)
            )
        )
        .scalars()
        .all()
    )

    # Идём от старых к новым: последняя запись перетирает порцию, а счётчик
    # растёт. Так в списке оказывается тот вес, который человек ел последним.
    seen: dict[str, tuple[int, Meal]] = {}
    for meal in rows:
        key = normalize(meal.name)
        if not key:
            continue
        times = seen[key][0] + 1 if key in seen else 1
        seen[key] = (times, meal)

    # Сначала то, что едят чаще; при равной частоте — то, что ели недавнее.
    # Сортировать готовые Favorite нельзя: в них уже нет времени записи, и
    # порядок молча выродился бы в «кто первым попался».
    # Скрытое отсеиваем здесь, а не на подходе: блюдо всё равно остаётся в
    # дневнике и в статистике — человек просил не предлагать его, а не
    # забыть, что он его ел.
    убрано = hidden or set()
    ranked = sorted(
        (pair for key, pair in seen.items()
         if pair[0] >= min_times and key not in убрано),
        key=lambda pair: (pair[0], pair[1].logged_at),
        reverse=True,
    )
    return [
        Favorite(
            name=meal.name,
            weight_g=round(meal.weight_g or 0),
            calories=round(meal.calories or 0),
            protein_g=round(meal.protein_g or 0),
            fat_g=round(meal.fat_g or 0),
            carbs_g=round(meal.carbs_g or 0),
            fiber_g=round(meal.fiber_g or 0),
            times=times,
        )
        for times, meal in ranked[:limit]
    ]


__all__ = ["DEFAULT_LIMIT", "Favorite", "frequent_meals", "hidden_names",
           "hide", "normalize", "restore"]
