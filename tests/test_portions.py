"""Тесты пересчёта порций и прогресс-бара (utils/portions.py, utils/progress.py)."""

import pytest

from utils.portions import MAX_WEIGHT_G, MIN_WEIGHT_G, adjust_weight, clamp_weight, scale_nutrition
from utils.progress import format_remaining, render_progress_bar

NUTRITION = {"calories": 300.0, "protein_g": 10.0, "fat_g": 8.0, "carbs_g": 45.0,
             "fiber_g": 6.0}


def test_scale_nutrition_doubles_with_weight():
    scaled = scale_nutrition(NUTRITION, from_weight_g=200, to_weight_g=400)
    assert scaled == {"calories": 600.0, "protein_g": 20.0, "fat_g": 16.0, "carbs_g": 90.0,
                      "fiber_g": 12.0}


def test_scale_nutrition_halves_with_weight():
    scaled = scale_nutrition(NUTRITION, from_weight_g=200, to_weight_g=100)
    assert scaled["calories"] == 150.0
    assert scaled["carbs_g"] == 22.5


def test_scale_nutrition_same_weight_is_identity():
    scaled = scale_nutrition(NUTRITION, from_weight_g=250, to_weight_g=250)
    assert scaled == NUTRITION


def test_scale_nutrition_scales_fiber_too():
    """Клетчатка пересчитывается вместе с остальным — она часть порции."""
    scaled = scale_nutrition(NUTRITION, from_weight_g=200, to_weight_g=300)
    assert scaled["fiber_g"] == 9.0


def test_scale_nutrition_missing_fiber_becomes_zero():
    """Записи, сделанные до появления клетчатки, не ломают пересчёт."""
    old_meal = {"calories": 300.0, "protein_g": 10.0, "fat_g": 8.0, "carbs_g": 45.0}
    assert scale_nutrition(old_meal, from_weight_g=200, to_weight_g=400)["fiber_g"] == 0.0


@pytest.mark.parametrize("from_w,to_w", [(0, 100), (100, 0), (-5, 100)])
def test_scale_nutrition_rejects_non_positive_weights(from_w, to_w):
    with pytest.raises(ValueError):
        scale_nutrition(NUTRITION, from_weight_g=from_w, to_weight_g=to_w)


def test_adjust_weight_steps_by_25_percent():
    assert adjust_weight(200, bigger=True) == 250
    assert adjust_weight(200, bigger=False) == 150


def test_adjust_weight_clamps_to_range():
    assert adjust_weight(MIN_WEIGHT_G, bigger=False) == MIN_WEIGHT_G
    assert adjust_weight(MAX_WEIGHT_G, bigger=True) == MAX_WEIGHT_G


def test_adjust_weight_rejects_non_positive():
    with pytest.raises(ValueError):
        adjust_weight(0, bigger=True)


def test_clamp_weight_bounds():
    assert clamp_weight(1) == MIN_WEIGHT_G
    assert clamp_weight(99999) == MAX_WEIGHT_G
    assert clamp_weight(250) == 250


def test_progress_bar_half_full():
    bar = render_progress_bar(900, 1800, width=10)
    assert bar == "▓▓▓▓▓░░░░░ 50%"


def test_progress_bar_does_not_overflow_when_over_norm():
    bar = render_progress_bar(2400, 1800, width=10)
    assert bar.startswith("▓" * 10)
    assert "133%" in bar
    # Ширина шкалы не меняется при переборе.
    assert bar.count("▓") + bar.count("░") == 10


def test_progress_bar_without_norm():
    assert render_progress_bar(500, 0) == "░" * 10 + " —"


def test_format_remaining_reports_deficit_and_excess():
    assert format_remaining(1320, 1800) == "осталось 480"
    assert format_remaining(1900, 1800) == "перебор на 100"
