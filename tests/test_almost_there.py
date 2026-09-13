"""«Остался один шаг» — самый сильный повод написать.

Обычная подсказка тем весомее, чем больше не хватает: не отмечено ни глотка
воды — повод серьёзный. «Остался шаг» устроен наоборот: чем меньше осталось,
тем он сильнее. Маленькое усилие, понятная награда, одно действие — это
единственное сочетание, ради которого стоит побеспокоить телефон.

Здесь проверяется и то, что порог честный: «двадцать процентов» без предела
в миллилитрах превратили бы восемьсот миллилитров в «остался шаг».
"""

import pytest

from services.context import (ALMOST_CRYSTALS, ALMOST_STEPS, ALMOST_WATER_ML,
                              DayContext, _candidates, next_action)


def day(**over):
    base = dict(hour=15)
    base.update(over)
    return DayContext(**base)


def pick(ctx, code):
    return next((a for a in _candidates(ctx) if a.code == code), None)


# --- вода -----------------------------------------------------------------


def test_a_glass_from_the_finish_is_the_strongest_kind_of_nudge():
    close = day(water_ml=1800, water_target=2000)
    far = day(water_ml=0, water_target=2000)
    assert pick(close, "water").score > pick(far, "water").score


def test_the_button_offers_exactly_what_is_left():
    """«+250 мл» там, где до нормы 300, — это ещё один заход завтра."""
    action = pick(day(water_ml=1700, water_target=2000), "water")
    assert action.amount == 300
    assert action.cta == "+300 мл"
    assert "300" in action.text


def test_a_big_share_of_a_big_norm_is_not_one_step():
    """Двадцать процентов от четырёх литров — восемьсот миллилитров.

    Одной доли для порога мало: без предела в миллилитрах бот сказал бы
    «остался один стакан» там, где осталось почти два.
    """
    ctx = day(water_ml=3200, water_target=4000)
    action = pick(ctx, "water")
    assert action.amount == 250          # обычная подсказка, а не «остался шаг»
    assert action.score < 1.0


def test_a_finished_norm_says_nothing_at_all():
    assert pick(day(water_ml=2000, water_target=2000), "water") is None


# --- шаги -----------------------------------------------------------------


def test_almost_walked_beats_barely_started():
    close = day(steps=7200, steps_goal=8000, steps_logged=True)
    far = day(steps=500, steps_goal=8000, steps_logged=True)
    assert pick(close, "steps").score > pick(far, "steps").score
    assert "800" in pick(close, "steps").text


def test_the_step_threshold_has_a_floor_in_steps_too():
    # Двадцать процентов от тридцати тысяч — шесть тысяч шагов, это час ходьбы.
    far = day(steps=24000, steps_goal=30000, steps_logged=True)
    assert pick(far, "steps").score < 1.0


# --- день и уровень -------------------------------------------------------


def test_the_last_task_of_the_day_is_worth_saying():
    ctx = day(quests_total=5, quests_left=1)
    action = pick(ctx, "day")
    assert action is not None and action.score > 1.0
    assert action.target == "today"


def test_a_day_with_plenty_left_is_not_almost_done():
    assert pick(day(quests_total=5, quests_left=3), "day") is None


def test_a_closed_day_is_not_nagged():
    assert pick(day(quests_total=5, quests_left=0), "day") is None


def test_a_level_within_reach_is_mentioned_gently():
    action = pick(day(crystals_left=ALMOST_CRYSTALS), "level")
    assert action is not None
    # Слабее всех остальных «остался шаг»: награда приятная, но не сегодняшняя.
    assert action.score < pick(day(quests_total=5, quests_left=1), "day").score


def test_a_level_far_away_is_not_mentioned():
    assert pick(day(crystals_left=ALMOST_CRYSTALS + 40), "level") is None


# --- как это влияет на выбор ----------------------------------------------


def test_one_step_left_outranks_an_ordinary_shortfall():
    """Из двух поводов побеждает тот, где до награды ближе."""
    ctx = day(water_ml=1800, water_target=2000,
              protein_g=20, protein_target=100)
    assert next_action(ctx).code == "water"


def test_the_nudge_is_loud_enough_to_reach_the_phone():
    """Порог, ниже которого движок молчит, — 0.6 на «сбалансированно»."""
    from services.notifications import MIN_SCORE

    for ctx, code in (
        (day(water_ml=1800, water_target=2000), "water"),
        (day(steps=7200, steps_goal=8000, steps_logged=True), "steps"),
        (day(quests_total=5, quests_left=1), "day"),
    ):
        assert pick(ctx, code).score > MIN_SCORE["balanced"], code


@pytest.mark.parametrize("key", ["water_almost", "steps_almost", "day_almost",
                                 "level_almost"])
def test_every_almost_intent_has_several_wordings(key):
    from services.context import VARIANTS

    assert len(VARIANTS[key]) >= 5
