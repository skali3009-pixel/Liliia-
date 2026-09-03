"""Формулы для расчёта суточной нормы калорий, БЖУ и воды.

Источники и допущения:
- BMR (базовый обмен веществ) считается по формуле Миффлина-Сан Жеора —
  общепризнанно самая точная классическая формула для здоровых взрослых
  (точнее устаревшей Харриса-Бенедикта).
- TDEE (суточный расход энергии) = BMR * коэффициент активности
  (стандартная 5-уровневая шкала).
- Калорийность под цель — это TDEE, скорректированный на дефицит/профицит.
- Белок и жир считаются в граммах на кг текущего веса тела (упрощение для
  MVP: без разделения на тощую массу тела); углеводы — остаток калорий.
- Норма воды — 30-40 мл/кг веса, нижняя граница для низкой активности,
  верхняя — для высокой (плюс дополнительная жидкость на тренировках).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"


class ActivityLevel(str, Enum):
    SEDENTARY = "sedentary"      # сидячий образ жизни, тренировок нет
    LIGHT = "light"              # лёгкая активность, 1-3 тренировки/нед
    MODERATE = "moderate"        # умеренная активность, 3-5 тренировок/нед
    HIGH = "high"                # высокая активность, 6-7 тренировок/нед
    VERY_HIGH = "very_high"      # очень высокая (спорт + физическая работа)


class Goal(str, Enum):
    LOSE_WEIGHT = "lose_weight"      # похудение
    MAINTAIN = "maintain"            # поддержание
    GAIN_MASS = "gain_mass"          # набор массы
    RECOMPOSITION = "recomposition"  # рельеф (сушка / рекомпозиция)


# Коэффициенты активности Миффлина-Сан Жеора.
ACTIVITY_MULTIPLIERS: dict[ActivityLevel, float] = {
    ActivityLevel.SEDENTARY: 1.2,
    ActivityLevel.LIGHT: 1.375,
    ActivityLevel.MODERATE: 1.55,
    ActivityLevel.HIGH: 1.725,
    ActivityLevel.VERY_HIGH: 1.9,
}

# Норма воды, мл на кг веса — растёт вместе с уровнем активности.
WATER_ML_PER_KG: dict[ActivityLevel, float] = {
    ActivityLevel.SEDENTARY: 30.0,
    ActivityLevel.LIGHT: 32.5,
    ActivityLevel.MODERATE: 35.0,
    ActivityLevel.HIGH: 37.5,
    ActivityLevel.VERY_HIGH: 40.0,
}

# Множитель калорийности относительно TDEE (дефицит/профицит под цель).
GOAL_CALORIE_FACTOR: dict[Goal, float] = {
    Goal.LOSE_WEIGHT: 0.80,      # дефицит ~20%
    Goal.MAINTAIN: 1.00,
    Goal.GAIN_MASS: 1.12,        # профицит ~12%
    Goal.RECOMPOSITION: 0.90,    # мягкий дефицит ~10%, акцент на белок
}

# Белок, г на кг веса тела — по цели.
GOAL_PROTEIN_G_PER_KG: dict[Goal, float] = {
    Goal.LOSE_WEIGHT: 2.0,
    Goal.MAINTAIN: 1.6,
    Goal.GAIN_MASS: 1.8,
    Goal.RECOMPOSITION: 2.2,
}

# Жир, г на кг веса тела — по цели (не ниже физиологического минимума).
GOAL_FAT_G_PER_KG: dict[Goal, float] = {
    Goal.LOSE_WEIGHT: 0.8,
    Goal.MAINTAIN: 1.0,
    Goal.GAIN_MASS: 1.0,
    Goal.RECOMPOSITION: 0.9,
}

KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_FAT = 9
KCAL_PER_G_CARBS = 4


@dataclass(frozen=True)
class Macros:
    calories: int
    protein_g: int
    fat_g: int
    carbs_g: int


def bmr_mifflin_st_jeor(
    *, gender: Gender, weight_kg: float, height_cm: float, age_years: int
) -> float:
    """Базовый обмен веществ (BMR), ккал/сутки, по формуле Миффлина-Сан Жеора.

    Мужчины: 10*вес + 6.25*рост - 5*возраст + 5
    Женщины: 10*вес + 6.25*рост - 5*возраст - 161
    """
    if weight_kg <= 0 or height_cm <= 0 or age_years <= 0:
        raise ValueError("weight_kg, height_cm и age_years должны быть положительными")

    base = 10 * weight_kg + 6.25 * height_cm - 5 * age_years
    return base + 5 if gender == Gender.MALE else base - 161


def tdee(*, bmr: float, activity_level: ActivityLevel) -> float:
    """Суточный расход энергии (TDEE) = BMR * коэффициент активности."""
    return bmr * ACTIVITY_MULTIPLIERS[activity_level]


def daily_water_ml(*, weight_kg: float, activity_level: ActivityLevel) -> int:
    """Суточная норма воды, мл (30-40 мл/кг в зависимости от активности)."""
    if weight_kg <= 0:
        raise ValueError("weight_kg должен быть положительным")
    return round(weight_kg * WATER_ML_PER_KG[activity_level])


def calculate_macros(
    *,
    gender: Gender,
    weight_kg: float,
    height_cm: float,
    age_years: int,
    activity_level: ActivityLevel,
    goal: Goal,
) -> Macros:
    """Полный расчёт суточной нормы калорий и БЖУ под цель пользователя."""
    bmr = bmr_mifflin_st_jeor(
        gender=gender, weight_kg=weight_kg, height_cm=height_cm, age_years=age_years
    )
    maintenance_calories = tdee(bmr=bmr, activity_level=activity_level)
    calories = maintenance_calories * GOAL_CALORIE_FACTOR[goal]

    protein_g = GOAL_PROTEIN_G_PER_KG[goal] * weight_kg
    fat_g = GOAL_FAT_G_PER_KG[goal] * weight_kg
    protein_kcal = protein_g * KCAL_PER_G_PROTEIN
    fat_kcal = fat_g * KCAL_PER_G_FAT

    # Углеводы — весь остаток калорий после белка и жира (не уходим в минус).
    carbs_kcal = max(calories - protein_kcal - fat_kcal, 0)
    carbs_g = carbs_kcal / KCAL_PER_G_CARBS

    return Macros(
        calories=round(calories),
        protein_g=round(protein_g),
        fat_g=round(fat_g),
        carbs_g=round(carbs_g),
    )
