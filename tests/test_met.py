"""Тесты расчёта потраченных калорий."""

import pytest

from utils.met import calories_burned, strength_exercise_calories, strength_exercise_minutes


def test_calories_follow_met_formula():
    # Бег трусцой (MET 7) 30 минут при весе 60 кг: 7 × 60 × 0.5 = 210 ккал.
    assert calories_burned(met=7, weight_kg=60, minutes=30) == pytest.approx(210)


def test_calories_scale_with_weight_and_time():
    light = calories_burned(met=5, weight_kg=50, minutes=20)
    heavy = calories_burned(met=5, weight_kg=80, minutes=20)
    longer = calories_burned(met=5, weight_kg=50, minutes=40)

    assert heavy > light
    assert longer == pytest.approx(light * 2)


@pytest.mark.parametrize("met,weight,minutes", [(0, 60, 30), (5, 0, 30), (5, 60, 0), (-5, 60, 30)])
def test_nonsense_input_gives_zero(met, weight, minutes):
    assert calories_burned(met=met, weight_kg=weight, minutes=minutes) == 0.0


def test_exercise_duration_counts_rest_between_sets_only():
    # 3 подхода по 12 повторов, отдых 60 с:
    # работа 3×12×3 = 108 с, отдых 2×60 = 120 с → 228 с = 3.8 мин.
    assert strength_exercise_minutes(sets=3, reps=12, rest_seconds=60) == pytest.approx(3.8)


def test_single_set_has_no_rest():
    assert strength_exercise_minutes(sets=1, reps=10, rest_seconds=90) == pytest.approx(0.5)


def test_strength_exercise_calories_are_reasonable():
    # Приседания (MET 5) 3×12 с отдыхом 60 с при весе 62 кг — около 20 ккал.
    burned = strength_exercise_calories(met=5, weight_kg=62, sets=3, reps=12, rest_seconds=60)
    assert 15 < burned < 25


def test_timed_exercise_counts_seconds_not_reps():
    from utils.met import timed_exercise_minutes

    # Планка: 3 подхода по 30 секунд, отдых 45 с →
    # работа 90 с + отдых 90 с = 180 с = 3 минуты.
    assert timed_exercise_minutes(sets=3, seconds_per_set=30, rest_seconds=45) == pytest.approx(3.0)


def test_timed_exercise_is_longer_than_single_rep_estimate():
    from utils.met import timed_exercise_minutes

    timed = timed_exercise_minutes(sets=3, seconds_per_set=30, rest_seconds=45)
    as_one_rep = strength_exercise_minutes(sets=3, reps=1, rest_seconds=45)
    assert timed > as_one_rep
