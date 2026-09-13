"""Момент, когда человек дошёл до своей цели.

До сих пор его не было вовсе. Человек ставил цель в анкете, месяцами к ней
шёл — и в день, когда весы показывали нужное число, не происходило ничего.
Приложение молча продолжало считать дефицит, как будто ничего не случилось.

Это не только обидно, это ещё и вредно. Норма калорий считается под цель:
пока цель «похудение», человек остаётся в дефиците и после того, как худеть
уже некуда. Так и уезжают в недоедание — не сорвавшись, а наоборот,
старательно продолжая делать то, что говорит приложение.

Поэтому здесь две вещи сразу: заметить и предложить перейти на поддержание.
Решает человек — приложение только спрашивает.
"""

from __future__ import annotations

from dataclasses import dataclass

from models import GoalEnum, User

# Насколько близко к цели считаем, что она взята. Весы за день гуляют на
# полкило от воды и соли, поэтому ловить точное совпадение бессмысленно.
TOLERANCE_KG = 0.3

# Цели, у которых вообще есть «дошёл»: у поддержания и рекомпозиции числа
# на весах не финиш, и объявлять там победу не о чем.
GOALS_WITH_FINISH = (GoalEnum.LOSE_WEIGHT, GoalEnum.GAIN_MASS)


def reached(user: User, weight_kg: float | None) -> bool:
    """Дошёл ли человек до целевого веса."""
    target = user.target_weight_kg
    if not target or not weight_kg or user.goal not in GOALS_WITH_FINISH:
        return False

    if user.goal == GoalEnum.LOSE_WEIGHT:
        return weight_kg <= target + TOLERANCE_KG
    return weight_kg >= target - TOLERANCE_KG


@dataclass(frozen=True)
class Arrival:
    """Что сказать человеку, который дошёл."""

    weight_kg: float
    target_kg: float
    started_kg: float | None

    @property
    def change_kg(self) -> float:
        return abs((self.started_kg or self.weight_kg) - self.weight_kg)


def render(arrival: Arrival) -> str:
    """Поздравление и один вопрос. Без «а теперь давай ещё пять килограммов»."""
    lines = ["🎯 Ты дошла до своей цели.", ""]
    if arrival.change_kg >= 0.5:
        lines.append(f"Было {arrival.started_kg:g}, стало {arrival.weight_kg:g} — "
                     f"это {arrival.change_kg:.1f} кг пути.")
    else:
        lines.append(f"На весах {arrival.weight_kg:g} кг — ровно то, к чему шла.")

    lines += [
        "",
        "Дальше важное. Норма калорий считается под цель, и пока в анкете стоит "
        "«похудение», я продолжу держать тебя в дефиците — хотя худеть больше "
        "некуда. Так и уезжают в недоедание: не сорвавшись, а старательно "
        "продолжая.",
        "",
        "Предлагаю перейти на поддержание: норма пересчитается вверх, еда "
        "станет спокойнее, вес останется. Если хочешь дальше — поставь новую "
        "цель сама, но сделай это осознанно.",
    ]
    return "\n".join(lines)


__all__ = ["GOALS_WITH_FINISH", "TOLERANCE_KG", "Arrival", "reached", "render"]
