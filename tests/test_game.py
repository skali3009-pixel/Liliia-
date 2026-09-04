"""Тесты игрового слоя: задания дня, опыт, уровни и награды."""

import pytest

from utils.game import (
    build_quests,
    crystal_stage,
    day_xp,
    earned_codes,
    level_from_xp,
    xp_for_level,
)

FULL_DAY = dict(
    meals_count=3,
    calories=1600,
    calories_norm=1662,
    water_ml=2200,
    water_norm_ml=2170,
    fiber_g=25,
    fiber_norm_g=23,
    workouts_today=1,
    days_since_measure=0,
)

EMPTY_DAY = dict(
    meals_count=0,
    calories=0,
    calories_norm=1662,
    water_ml=0,
    water_norm_ml=2170,
    fiber_g=0,
    fiber_norm_g=23,
    workouts_today=0,
    days_since_measure=0,
)


def codes(quests, *, done_only=True):
    return [q.code for q in quests if q.done or not done_only]


def test_full_day_closes_every_quest():
    quests = build_quests(**FULL_DAY)
    assert codes(quests) == ["meals", "water", "calories", "fiber", "move"]
    assert day_xp(quests) == 80


def test_empty_day_closes_nothing():
    quests = build_quests(**EMPTY_DAY)
    assert codes(quests) == []
    assert day_xp(quests) == 0


def test_undereating_does_not_close_the_calorie_quest():
    """Недобор — такой же промах, как перебор: 500 из 1662 не считается."""
    quests = build_quests(**{**FULL_DAY, "calories": 500})
    assert "calories" not in codes(quests)


def test_overeating_does_not_close_the_calorie_quest():
    quests = build_quests(**{**FULL_DAY, "calories": 2400})
    assert "calories" not in codes(quests)


def test_measure_quest_appears_only_when_it_is_time():
    fresh = build_quests(**{**FULL_DAY, "days_since_measure": 2})
    assert "measure" not in codes(fresh, done_only=False)

    due = build_quests(**{**FULL_DAY, "days_since_measure": 8})
    assert "measure" in codes(due, done_only=False)

    never = build_quests(**{**FULL_DAY, "days_since_measure": None})
    assert "measure" in codes(never, done_only=False)


def test_quest_progress_share_is_clamped():
    quests = {q.code: q for q in build_quests(**{**EMPTY_DAY, "water_ml": 1085})}
    assert quests["water"].share == 0.5
    assert quests["water"].hint == "1,1 из 2,2 л"

    overflow = {q.code: q for q in build_quests(**{**EMPTY_DAY, "water_ml": 9000})}
    assert overflow["water"].share == 1.0


def test_zero_norms_do_not_hand_out_free_quests():
    """Пока профиль не настроен, задания по норме не считаются выполненными."""
    quests = build_quests(
        **{**EMPTY_DAY, "calories_norm": 0, "water_norm_ml": 0, "fiber_norm_g": 0}
    )
    assert codes(quests) == []


def test_levels_get_more_expensive():
    assert xp_for_level(1) == 100
    assert xp_for_level(2) == 150
    assert xp_for_level(3) == 200


def test_level_from_xp_counts_progress_inside_the_level():
    assert level_from_xp(0) == level_from_xp(0)
    first = level_from_xp(40)
    assert (first.number, first.xp_in_level, first.xp_to_next) == (1, 40, 100)

    second = level_from_xp(100)
    assert (second.number, second.xp_in_level, second.xp_to_next) == (2, 0, 150)

    third = level_from_xp(260)
    assert (third.number, third.xp_in_level, third.xp_to_next) == (3, 10, 200)


def test_level_share_is_a_fraction():
    assert level_from_xp(50).share == 0.5


@pytest.mark.parametrize("level,stage", [(1, 1), (4, 1), (5, 2), (17, 5), (99, 5)])
def test_crystal_grows_with_level_and_stops_at_five(level, stage):
    assert crystal_stage(level) == stage


def test_awards_are_earned_by_milestones():
    earned = earned_codes(
        meals_total=42, streak=8, level=5, weight_lost_kg=1.4,
        waist_lost_cm=5, workouts_total=12,
    )
    assert earned == {"first_step", "streak_7", "level_5", "minus_1kg", "waist_5cm",
                      "workouts_10"}


def test_nothing_is_earned_on_an_empty_profile():
    assert earned_codes(
        meals_total=0, streak=0, level=1, weight_lost_kg=0, waist_lost_cm=0,
        workouts_total=0,
    ) == set()
