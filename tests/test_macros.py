"""Тесты остатка нормы и определения недобора."""

from utils.macros import dominant_gap, remaining

NORMS = {"calories": 1600, "protein_g": 120, "fat_g": 48, "carbs_g": 160}


def test_remaining_subtracts_eaten():
    left = remaining({"calories": 600, "protein_g": 40, "fat_g": 20, "carbs_g": 60}, NORMS)
    assert (left.calories, left.protein_g, left.fat_g, left.carbs_g) == (1000, 80, 28, 100)


def test_overshoot_shows_zero_not_negative():
    left = remaining({"calories": 1900, "protein_g": 130, "fat_g": 60, "carbs_g": 200}, NORMS)
    assert (left.calories, left.protein_g, left.fat_g, left.carbs_g) == (0, 0, 0, 0)
    assert left.all_done is True


def test_empty_day_leaves_full_norm():
    left = remaining({}, NORMS)
    assert left.calories == 1600 and left.protein_g == 120


def test_gap_is_measured_in_shares_not_grams():
    """40 г белка из 120 — недобор больше, чем 40 г углеводов из 160."""
    left = remaining({"calories": 900, "protein_g": 80, "fat_g": 40, "carbs_g": 120}, NORMS)
    assert dominant_gap(left, NORMS) == "protein_g"


def test_no_gap_when_everything_nearly_eaten():
    left = remaining({"calories": 1500, "protein_g": 115, "fat_g": 45, "carbs_g": 152}, NORMS)
    assert dominant_gap(left, NORMS) is None


def test_carbs_gap_detected():
    left = remaining({"calories": 800, "protein_g": 110, "fat_g": 44, "carbs_g": 40}, NORMS)
    assert dominant_gap(left, NORMS) == "carbs_g"
