"""Формулы для расчёта суточной нормы калорий, БЖУ и воды.

Источники и допущения:
- BMR (базовый обмен веществ) считается по формуле Миффлина-Сан Жеора —
  общепризнанно самая точная классическая формула для здоровых взрослых
  (точнее устаревшей Харриса-Бенедикта).
- TDEE (суточный расход энергии) = BMR * коэффициент активности
  (стандартная 5-уровневая шкала).
- Калорийность под цель — это TDEE, скорректированный на дефицит/профицит.
- Белок и жир считаются в граммах на кг РАСЧЁТНОГО веса, а не того, что на
  весах. При большом весе брать фактический нельзя: жировая ткань белка почти
  не требует, и цель получается недостижимой. Расчётный вес = верх здорового
  диапазона для роста плюс 40% разницы до фактического — общепринятый в
  клинической практике приём.
- Сверху стоят предохранители: белок и жир не больше трети калорий каждый,
  углеводам всегда остаётся не меньше 15% рациона, вода не больше трёх литров,
  калорийность не ниже физиологического минимума. Норма, которую нельзя
  выполнить, — это не строгая норма, а сломанная.
- Норма воды — 30-40 мл/кг веса, нижняя граница для низкой активности,
  верхняя — для высокой (плюс дополнительная жидкость на тренировках).
- Клетчатка не входит в калорийность и не делит калории с БЖУ: это отдельный
  ориентир, 14 г на 1000 ккал (Dietary Guidelines for Americans). На дефиците
  пропорция даёт слишком мало, поэтому норма не опускается ниже 20 г и не
  поднимается выше 40 г (ВОЗ рекомендует взрослым не меньше 25 г).
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

# Клетчатка: г на 1000 ккал рациона и границы разумного диапазона.
FIBER_G_PER_1000_KCAL = 14.0
MIN_FIBER_G = 20
MAX_FIBER_G = 40

# --- Предохранители ---------------------------------------------------------
# Всё, что ниже, появилось после разбора живого случая: женщине 120 кг
# приложение выдало 240 г белка, 3606 мл воды и 0 г углеводов. Формула не
# сломалась — она честно вернула ноль, потому что белок с жиром съели весь
# бюджет и вылезли за него на 3 ккал. Ни одну из трёх цифр выполнить нельзя.

# Верх здорового диапазона веса по ИМТ — от него считается расчётный вес.
HEALTHY_BMI_MAX = 24.9
# Какую долю превышения над здоровым весом учитывать. 0.4 — клиническая норма
# для расчёта питания при ожирении.
EXCESS_WEIGHT_SHARE = 0.4

# Ни белок, ни жир не могут занимать больше трети рациона.
MAX_PROTEIN_SHARE = 0.35
MAX_FAT_SHARE = 0.35
# И углеводам всегда остаётся хотя бы столько.
MIN_CARB_SHARE = 0.15

# Вода: разумные границы вместо линейного роста без конца.
MIN_WATER_ML = 1500
MAX_WATER_ML = 3000

# Ниже этого приложение не имеет права опускать суточную норму.
MIN_CALORIES = {Gender.FEMALE: 1200, Gender.MALE: 1500}

KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_FAT = 9
KCAL_PER_G_CARBS = 4


@dataclass(frozen=True)
class Macros:
    calories: int
    protein_g: int
    fat_g: int
    carbs_g: int
    fiber_g: int


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


def reference_weight_kg(*, weight_kg: float, height_cm: float) -> float:
    """Вес, от которого считать питание.

    Пока человек в пределах здорового диапазона — это его собственный вес.
    Выше — берём верх диапазона плюс 40% превышения: жировая ткань требует
    и белка, и воды заметно меньше, чем мышечная, и считать по весам значит
    выдать цель, которую невозможно выполнить.
    """
    if height_cm <= 0:
        return weight_kg
    healthy_max = HEALTHY_BMI_MAX * (height_cm / 100) ** 2
    if weight_kg <= healthy_max:
        return weight_kg
    return healthy_max + (weight_kg - healthy_max) * EXCESS_WEIGHT_SHARE


def daily_water_ml(*, weight_kg: float, activity_level: ActivityLevel,
                   height_cm: float | None = None) -> int:
    """Суточная норма воды, мл (30-40 мл/кг в зависимости от активности).

    С верхней границей: три литра — это уже много, а линейная формула на
    большом весе выдавала три с половиной и больше.
    """
    if weight_kg <= 0:
        raise ValueError("weight_kg должен быть положительным")
    base = weight_kg if height_cm is None else reference_weight_kg(
        weight_kg=weight_kg, height_cm=height_cm)
    raw = base * WATER_ML_PER_KG[activity_level]
    return round(min(max(raw, MIN_WATER_ML), MAX_WATER_ML))


def daily_fiber_g(*, calories: float) -> int:
    """Суточная норма клетчатки, г — 14 г на 1000 ккал, но в границах 20-40 г.

    Клетчатка не даёт калорий и не вычитается из углеводов: это отдельный
    показатель, у которого своя дневная цель.
    """
    if calories <= 0:
        raise ValueError("calories должен быть положительным")
    proportional = calories / 1000 * FIBER_G_PER_1000_KCAL
    return round(min(max(proportional, MIN_FIBER_G), MAX_FIBER_G))


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
    # Ниже физиологического минимума приложение никого не отправляет, какой бы
    # ни была цель: это уже не дефицит, а голодание.
    calories = max(calories, MIN_CALORIES[gender])

    # Считаем от расчётного веса, а не от того, что на весах.
    base_kg = reference_weight_kg(weight_kg=weight_kg, height_cm=height_cm)
    protein_g = GOAL_PROTEIN_G_PER_KG[goal] * base_kg
    fat_g = GOAL_FAT_G_PER_KG[goal] * base_kg

    # Ни белок, ни жир не могут занять больше трети рациона.
    protein_g = min(protein_g, calories * MAX_PROTEIN_SHARE / KCAL_PER_G_PROTEIN)
    fat_g = min(fat_g, calories * MAX_FAT_SHARE / KCAL_PER_G_FAT)

    # И углеводам всегда остаётся место. Если не остаётся — ужимаем белок и
    # жир вместе, а не обнуляем углеводы: ноль в норме означает, что норма
    # невыполнима, и человек это видит.
    room_for_carbs = calories * MIN_CARB_SHARE
    used = protein_g * KCAL_PER_G_PROTEIN + fat_g * KCAL_PER_G_FAT
    if used > calories - room_for_carbs:
        shrink = (calories - room_for_carbs) / used
        protein_g *= shrink
        fat_g *= shrink

    carbs_kcal = calories - protein_g * KCAL_PER_G_PROTEIN - fat_g * KCAL_PER_G_FAT
    carbs_g = carbs_kcal / KCAL_PER_G_CARBS

    return Macros(
        calories=round(calories),
        protein_g=round(protein_g),
        fat_g=round(fat_g),
        carbs_g=round(carbs_g),
        fiber_g=daily_fiber_g(calories=calories),
    )
