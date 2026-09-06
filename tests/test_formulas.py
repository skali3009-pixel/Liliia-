"""Тесты формул расчёта КБЖУ и нормы воды (utils/formulas.py)."""

import pytest

from utils.formulas import (
    MAX_FIBER_G,
    MIN_FIBER_G,
    ActivityLevel,
    Gender,
    Goal,
    bmr_mifflin_st_jeor,
    calculate_macros,
    daily_fiber_g,
    daily_water_ml,
    tdee,
)


def test_bmr_male_reference_values():
    # 30-летний мужчина, 80 кг, 180 см:
    # 10*80 + 6.25*180 - 5*30 + 5 = 800 + 1125 - 150 + 5 = 1780
    bmr = bmr_mifflin_st_jeor(gender=Gender.MALE, weight_kg=80, height_cm=180, age_years=30)
    assert bmr == pytest.approx(1780.0)


def test_bmr_female_reference_values():
    # 25-летняя женщина, 60 кг, 165 см:
    # 10*60 + 6.25*165 - 5*25 - 161 = 600 + 1031.25 - 125 - 161 = 1345.25
    bmr = bmr_mifflin_st_jeor(gender=Gender.FEMALE, weight_kg=60, height_cm=165, age_years=25)
    assert bmr == pytest.approx(1345.25)


@pytest.mark.parametrize("weight_kg,height_cm,age_years", [(0, 180, 30), (80, 0, 30), (80, 180, 0)])
def test_bmr_rejects_non_positive_inputs(weight_kg, height_cm, age_years):
    with pytest.raises(ValueError):
        bmr_mifflin_st_jeor(
            gender=Gender.MALE, weight_kg=weight_kg, height_cm=height_cm, age_years=age_years
        )


def test_tdee_applies_activity_multiplier():
    assert tdee(bmr=1780, activity_level=ActivityLevel.SEDENTARY) == pytest.approx(1780 * 1.2)
    assert tdee(bmr=1780, activity_level=ActivityLevel.VERY_HIGH) == pytest.approx(1780 * 1.9)


def test_daily_water_ml_scales_with_activity():
    sedentary = daily_water_ml(weight_kg=70, activity_level=ActivityLevel.SEDENTARY)
    very_high = daily_water_ml(weight_kg=70, activity_level=ActivityLevel.VERY_HIGH)
    assert sedentary == 2100  # 70 * 30
    assert very_high == 2800  # 70 * 40
    assert very_high > sedentary


def test_daily_water_ml_rejects_non_positive_weight():
    with pytest.raises(ValueError):
        daily_water_ml(weight_kg=0, activity_level=ActivityLevel.LIGHT)


def test_calculate_macros_lose_weight_is_below_maintenance():
    maintain = calculate_macros(
        gender=Gender.FEMALE,
        weight_kg=60,
        height_cm=165,
        age_years=25,
        activity_level=ActivityLevel.MODERATE,
        goal=Goal.MAINTAIN,
    )
    lose_weight = calculate_macros(
        gender=Gender.FEMALE,
        weight_kg=60,
        height_cm=165,
        age_years=25,
        activity_level=ActivityLevel.MODERATE,
        goal=Goal.LOSE_WEIGHT,
    )
    assert lose_weight.calories < maintain.calories
    # Похудение — более высокий белок на кг веса, чем поддержание.
    assert lose_weight.protein_g > maintain.protein_g


def test_calculate_macros_gain_mass_is_above_maintenance():
    maintain = calculate_macros(
        gender=Gender.MALE,
        weight_kg=80,
        height_cm=180,
        age_years=30,
        activity_level=ActivityLevel.HIGH,
        goal=Goal.MAINTAIN,
    )
    gain_mass = calculate_macros(
        gender=Gender.MALE,
        weight_kg=80,
        height_cm=180,
        age_years=30,
        activity_level=ActivityLevel.HIGH,
        goal=Goal.GAIN_MASS,
    )
    assert gain_mass.calories > maintain.calories


def test_calculate_macros_carbs_never_negative():
    # Экстремально низкая калорийность не должна давать отрицательные углеводы.
    macros = calculate_macros(
        gender=Gender.FEMALE,
        weight_kg=45,
        height_cm=150,
        age_years=60,
        activity_level=ActivityLevel.SEDENTARY,
        goal=Goal.LOSE_WEIGHT,
    )
    assert macros.carbs_g >= 0


def test_fiber_norm_scales_with_calories():
    """14 г клетчатки на 1000 ккал — стандартный ориентир."""
    assert daily_fiber_g(calories=2000) == 28


def test_fiber_norm_has_floor_and_ceiling():
    # На жёстком дефиците пропорция даёт слишком мало — держим нижнюю границу.
    assert daily_fiber_g(calories=1000) == MIN_FIBER_G
    # И не требуем невыполнимого на очень калорийном рационе.
    assert daily_fiber_g(calories=4000) == MAX_FIBER_G


def test_fiber_norm_is_not_part_of_calories():
    """Клетчатка идёт отдельно и не отнимает калории у БЖУ."""
    macros = calculate_macros(
        gender=Gender.FEMALE,
        weight_kg=62,
        height_cm=165,
        age_years=30,
        activity_level=ActivityLevel.MODERATE,
        goal=Goal.LOSE_WEIGHT,
    )
    assert macros.fiber_g > 0
    recomputed = macros.protein_g * 4 + macros.fat_g * 9 + macros.carbs_g * 4
    assert recomputed == pytest.approx(macros.calories, abs=5)


def test_calculate_macros_macros_sum_to_calories():
    macros = calculate_macros(
        gender=Gender.MALE,
        weight_kg=80,
        height_cm=180,
        age_years=30,
        activity_level=ActivityLevel.MODERATE,
        goal=Goal.MAINTAIN,
    )
    recomputed_calories = macros.protein_g * 4 + macros.fat_g * 9 + macros.carbs_g * 4
    assert recomputed_calories == pytest.approx(macros.calories, abs=5)


# --- Предохранители: норма обязана быть выполнимой -------------------------
# Появилось после живого случая: женщине 120 кг приложение выдало 240 г белка,
# 3606 мл воды и 0 г углеводов. Проверяем не один этот случай, а весь диапазон
# людей — чтобы класс ошибок закрылся целиком, а не один его представитель.

import itertools

from utils.formulas import (MAX_FAT_SHARE, MAX_PROTEIN_SHARE, MAX_WATER_ML,
                            MIN_CALORIES, MIN_CARB_SHARE, MIN_WATER_ML,
                            reference_weight_kg)

EVERYONE = list(itertools.product(
    [Gender.FEMALE, Gender.MALE],
    range(40, 201, 10),          # вес
    range(145, 201, 5),          # рост
    [18, 35, 60, 80],            # возраст
    list(ActivityLevel),
    list(Goal),
))


def test_no_target_is_ever_impossible_for_anyone():
    """Ни один человек не должен получить невыполнимую норму."""
    problems = []
    for gender, weight, height, age, activity, goal in EVERYONE:
        macros = calculate_macros(gender=gender, weight_kg=weight, height_cm=height,
                                  age_years=age, activity_level=activity, goal=goal)
        who = f"{gender.value} {weight}кг {height}см {age}л {activity.value} {goal.value}"

        if macros.carbs_g <= 0:
            problems.append(f"{who}: углеводы {macros.carbs_g} г")
        if macros.calories < MIN_CALORIES[gender]:
            problems.append(f"{who}: {macros.calories} ккал — ниже минимума")
        if macros.protein_g * 4 > macros.calories * (MAX_PROTEIN_SHARE + 0.01):
            problems.append(f"{who}: белок {macros.protein_g} г — больше трети рациона")
        if macros.fat_g * 9 > macros.calories * (MAX_FAT_SHARE + 0.01):
            problems.append(f"{who}: жир {macros.fat_g} г — больше трети рациона")
        if macros.carbs_g * 4 < macros.calories * (MIN_CARB_SHARE - 0.01):
            problems.append(f"{who}: углеводов меньше {MIN_CARB_SHARE:.0%} рациона")
        # Сумма макросов должна сходиться с калорийностью.
        total = macros.protein_g * 4 + macros.fat_g * 9 + macros.carbs_g * 4
        if abs(total - macros.calories) > macros.calories * 0.02:
            problems.append(f"{who}: БЖУ даёт {total:.0f} ккал вместо {macros.calories}")

    assert not problems, f"{len(problems)} нарушений, первые пять:\n" + \
        "\n".join(problems[:5])


def test_water_stays_within_reason_for_everyone():
    problems = []
    for gender, weight, height, age, activity, goal in EVERYONE:
        water = daily_water_ml(weight_kg=weight, height_cm=height,
                               activity_level=activity)
        if not MIN_WATER_ML <= water <= MAX_WATER_ML:
            problems.append(f"{weight}кг {height}см {activity.value}: {water} мл")
    assert not problems, f"вода вне разумного: {problems[:5]}"


def test_the_case_that_started_this():
    """Женщина 120 кг, 165 см, сидячая, худеет — тот самый профиль из отчёта."""
    macros = calculate_macros(gender=Gender.FEMALE, weight_kg=120.2, height_cm=165,
                              age_years=35, activity_level=ActivityLevel.SEDENTARY,
                              goal=Goal.LOSE_WEIGHT)
    water = daily_water_ml(weight_kg=120.2, height_cm=165,
                           activity_level=ActivityLevel.SEDENTARY)

    assert macros.carbs_g > 100, "углеводы снова обнулились"
    assert 130 <= macros.protein_g <= 180, f"белок {macros.protein_g} г"
    assert water <= MAX_WATER_ML, f"вода {water} мл"


def test_a_normal_weight_person_is_counted_by_their_own_weight():
    """Поправка касается только большого веса — остальных она не трогает."""
    assert reference_weight_kg(weight_kg=60, height_cm=165) == 60
    assert reference_weight_kg(weight_kg=45, height_cm=175) == 45
    # 120 кг при росте 165 — здоровый верх около 68, значит расчётный меньше 120.
    heavy = reference_weight_kg(weight_kg=120, height_cm=165)
    assert 80 < heavy < 100, heavy


def test_targets_still_grow_with_weight():
    """Предохранитель не должен превратить норму в константу."""
    light = calculate_macros(gender=Gender.FEMALE, weight_kg=60, height_cm=165,
                             age_years=35, activity_level=ActivityLevel.MODERATE,
                             goal=Goal.MAINTAIN)
    heavy = calculate_macros(gender=Gender.FEMALE, weight_kg=110, height_cm=165,
                             age_years=35, activity_level=ActivityLevel.MODERATE,
                             goal=Goal.MAINTAIN)
    assert heavy.protein_g > light.protein_g
    assert heavy.calories > light.calories
