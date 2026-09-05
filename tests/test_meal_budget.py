"""Тесты бюджета приёма пищи.

Главное, что здесь проверяется: остаток дня и бюджет одного приёма — это
разные числа. Раньше подбор видел только остаток и мог утром предложить
блюдо на весь день.
"""

from datetime import datetime

import pytest

from models import MealTypeEnum
from utils.meal_budget import LAST_MEAL_HOUR, MealBudget, meal_budget

NORM = 1800
LEFT = 1500        # человек съел мало — соблазн предложить всё сразу


def at(hour: int, minute: int = 20, *, left: float = LEFT, norm: float = NORM) -> MealBudget:
    return meal_budget(
        now=datetime(2026, 9, 5, hour, minute),
        daily_calories=norm,
        remaining_calories=left,
    )


def test_morning_meal_does_not_eat_the_whole_day():
    breakfast = at(8)
    assert breakfast.meal_type is MealTypeEnum.BREAKFAST
    assert breakfast.target_kcal < LEFT / 2
    assert breakfast.is_last is False


def test_lunch_gets_more_than_breakfast():
    assert at(13).target_kcal > at(8).target_kcal


def test_evening_uses_what_is_left():
    """После шести следующего приёма не будет — ориентир меняется на остаток."""
    day = at(13)
    evening = at(LAST_MEAL_HOUR + 1)

    assert evening.is_last is True
    assert evening.target_kcal > day.target_kcal


def test_evening_still_does_not_pile_the_whole_day_into_dinner():
    """Не ел весь день — это не повод советовать ужин на 1800 ккал."""
    evening = at(19, left=1800, norm=1800)
    assert evening.target_kcal <= 1800 * 0.45 + 50


def test_night_is_always_light():
    night = at(23)
    assert night.target_kcal <= 250
    assert "лёгк" in night.note.lower() or night.target_kcal <= 250


def test_small_remainder_asks_for_something_light():
    tight = at(19, left=120)
    assert tight.is_light is True
    assert "мало" in tight.note


def test_norm_used_up_suggests_stopping():
    done = at(20, left=0)
    assert done.target_kcal == 0
    assert "выбрана полностью" in done.note


def test_note_always_names_the_time_and_the_budget():
    for hour in (7, 12, 15, 19, 21):
        note = at(hour).note
        assert ":" in note                     # время названо
        assert "ккал" in note


def test_without_a_norm_falls_back_to_the_remainder():
    """Профиль без нормы — считаем по остатку, а не делим на ноль."""
    budget = meal_budget(
        now=datetime(2026, 9, 5, 13, 0), daily_calories=0, remaining_calories=600
    )
    assert budget.target_kcal > 0
