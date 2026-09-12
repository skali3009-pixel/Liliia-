"""Пересчёт КБЖУ при ручной коррекции порции.

Модель оценивает вес порции приблизительно, поэтому пользователь может
поправить его кнопками «больше/меньше» или ввести граммы вручную. КБЖУ при
этом пересчитывается пропорционально весу.
"""

from __future__ import annotations

# Шаг изменения порции по кнопке «➕/➖» — 25% от текущего веса.
PORTION_STEP = 0.25

MIN_WEIGHT_G = 5.0
MAX_WEIGHT_G = 3000.0

NUTRITION_KEYS = ("calories", "protein_g", "fat_g", "carbs_g", "fiber_g")


def clamp_weight(weight_g: float) -> float:
    """Ограничить вес порции разумным диапазоном."""
    return min(max(weight_g, MIN_WEIGHT_G), MAX_WEIGHT_G)


def adjust_weight(current_weight_g: float, *, bigger: bool, step: float = PORTION_STEP) -> float:
    """Увеличить или уменьшить вес порции на шаг (по умолчанию ±25%)."""
    if current_weight_g <= 0:
        raise ValueError("current_weight_g должен быть положительным")

    factor = (1 + step) if bigger else (1 - step)
    return clamp_weight(round(current_weight_g * factor))


def scale_nutrition(
    nutrition: dict[str, float], *, from_weight_g: float, to_weight_g: float
) -> dict[str, float]:
    """Пересчитать калории и БЖУ пропорционально новому весу порции.

    Возвращает новый словарь с ключами calories/protein_g/fat_g/carbs_g/fiber_g,
    округлёнными до одного знака.
    """
    if from_weight_g <= 0:
        raise ValueError("from_weight_g должен быть положительным")
    if to_weight_g <= 0:
        raise ValueError("to_weight_g должен быть положительным")

    factor = to_weight_g / from_weight_g
    return {key: round(float(nutrition.get(key, 0.0)) * factor, 1) for key in NUTRITION_KEYS}
