"""Определение типа приёма пищи по времени суток.

Чтобы не спрашивать пользователя лишний раз (минимум текста — максимум
кнопок), тип приёма пищи проставляется автоматически по времени записи.
"""

from __future__ import annotations

from datetime import datetime

from models import MealTypeEnum


def guess_meal_type(moment: datetime) -> MealTypeEnum:
    """Завтрак 5:00-10:59, обед 11:00-15:59, ужин 16:00-21:59, иначе перекус."""
    hour = moment.hour
    if 5 <= hour < 11:
        return MealTypeEnum.BREAKFAST
    if 11 <= hour < 16:
        return MealTypeEnum.LUNCH
    if 16 <= hour < 22:
        return MealTypeEnum.DINNER
    return MealTypeEnum.SNACK


MEAL_TYPE_RU = {
    MealTypeEnum.BREAKFAST: "завтрак",
    MealTypeEnum.LUNCH: "обед",
    MealTypeEnum.DINNER: "ужин",
    MealTypeEnum.SNACK: "перекус",
}
