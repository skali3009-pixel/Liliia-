"""Тесты формул расчёта КБЖУ и нормы воды (utils/formulas.py)."""

import pytest

from utils.formulas import (
    ActivityLevel,
    Gender,
    Goal,
    bmr_mifflin_st_jeor,
    calculate_macros,
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
