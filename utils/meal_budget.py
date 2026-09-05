"""Сколько калорий отдать одному приёму пищи.

Остаток за день и бюджет ближайшего приёма — разные числа, и путать их
нельзя. Если в обед сказать «осталось 1400 ккал», подбор честно предложит
блюдо на 1400 — и вечером есть станет нечего. Поэтому день делится между
приёмами по обычным долям, а к вечеру, когда следующего приёма уже не
будет, ориентиром становится сам остаток.

Здесь только арифметика и формулировки; сам подбор — в
services/suggestions.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from models import MealTypeEnum
from utils.meal_time import MEAL_TYPE_RU, guess_meal_type

# Привычное распределение суточной нормы по приёмам. Сумма меньше единицы:
# остаток — это перекусы, которые случаются между делом.
MEAL_SHARES: dict[MealTypeEnum, float] = {
    MealTypeEnum.BREAKFAST: 0.25,
    MealTypeEnum.LUNCH: 0.35,
    MealTypeEnum.DINNER: 0.30,
    MealTypeEnum.SNACK: 0.10,
}

# После этого часа следующего полноценного приёма уже не будет: считаем
# ужин последним и ориентируемся на остаток дня.
LAST_MEAL_HOUR = 18

# Ночью еда должна быть лёгкой независимо от остатка.
NIGHT_HOUR = 22
MORNING_HOUR = 5
NIGHT_MAX_KCAL = 250

# Даже если человек не ел весь день, сваливать всю норму в один ужин
# нельзя — это не то, что посоветует нутрициолог.
MAX_SINGLE_MEAL_SHARE = 0.45

# Ниже этого предлагать «полноценное блюдо» бессмысленно — только лёгкое.
LIGHT_LEFT_KCAL = 200
MIN_TARGET_KCAL = 120


@dataclass(frozen=True)
class MealBudget:
    """Бюджет ближайшего приёма пищи."""

    meal_type: MealTypeEnum
    target_kcal: int
    max_kcal: int
    is_last: bool
    is_light: bool
    note: str

    @property
    def meal_name(self) -> str:
        return MEAL_TYPE_RU[self.meal_type]


def _round50(value: float) -> int:
    return int(max(round(value / 50) * 50, 0))


def meal_budget(
    *, now: datetime, daily_calories: float, remaining_calories: float
) -> MealBudget:
    """Сколько калорий отдать ближайшему приёму и как это объяснить модели."""
    meal = guess_meal_type(now)
    left = max(float(remaining_calories), 0.0)
    norm = max(float(daily_calories), 0.0)
    clock = now.strftime("%H:%M")

    night = now.hour >= NIGHT_HOUR or now.hour < MORNING_HOUR
    day_closing = night or now.hour >= LAST_MEAL_HOUR

    if norm <= 0:
        target = left
    elif day_closing:
        # Следующего приёма не будет: ориентир — остаток, но в один приём
        # не больше разумной доли нормы.
        target = min(left, norm * MAX_SINGLE_MEAL_SHARE)
    else:
        target = min(norm * MEAL_SHARES[meal], left)

    if night:
        target = min(target, NIGHT_MAX_KCAL)

    is_light = left <= LIGHT_LEFT_KCAL
    target = max(target, 0.0)
    top = min(left, target * 1.25) if target else left

    if left <= 0:
        note = (
            f"Сейчас {clock}. Дневная норма уже выбрана полностью. "
            "Предложи что-то совсем лёгкое — овощи, зелень, немного белка — "
            "или честно скажи в поле why, что лучше остановиться."
        )
    elif is_light:
        note = (
            f"Сейчас {clock}, ближайший приём — {MEAL_TYPE_RU[meal]}. "
            f"На сегодня осталось всего {round(left)} ккал, это очень мало. "
            "Предлагай лёгкое: овощи, зелень, творог, кефир — уложись в остаток."
        )
    elif day_closing:
        note = (
            f"Сейчас {clock} — день закрывается, это последний приём пищи. "
            f"Ориентир: около {_round50(target)} ккал, но не больше "
            f"{_round50(top)} ккал. Остаток дня {round(left)} ккал целиком "
            "в один приём не сваливай: вечером еда должна быть легче, с белком "
            "и овощами."
        )
    else:
        note = (
            f"Сейчас {clock}, ближайший приём — {MEAL_TYPE_RU[meal]}. "
            f"Впереди сегодня ещё еда, поэтому на этот приём — около "
            f"{_round50(target)} ккал и не больше {_round50(top)} ккал. "
            f"Весь остаток дня ({round(left)} ккал) в одно блюдо не клади."
        )

    return MealBudget(
        meal_type=meal,
        target_kcal=_round50(max(target, MIN_TARGET_KCAL if left > 0 else 0)),
        max_kcal=_round50(top),
        is_last=day_closing,
        is_light=is_light,
        note=note,
    )


__all__ = [
    "LAST_MEAL_HOUR",
    "MEAL_SHARES",
    "MealBudget",
    "meal_budget",
]
