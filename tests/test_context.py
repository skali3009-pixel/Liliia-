"""Что предлагать человеку прямо сейчас.

Главное здесь — не то, что движок что-то предлагает, а то, что он молчит,
когда предлагать нечего, и не повторяет одно и то же весь день.
"""

import pytest

from services import context
from services.context import Action, DayContext, main_quest_codes, next_action


def day(**overrides) -> DayContext:
    """День, в котором всё в порядке. Тесты ломают по одному полю."""
    base = dict(
        hour=14, calories=1200, calories_target=1600,
        protein_g=95, protein_target=100,
        fiber_g=24, fiber_target=25,
        water_ml=2000, water_target=2100,
        meals_logged=3, workouts_today=1, days_since_measure=1,
        checkin_done=True,
    )
    base.update(overrides)
    return DayContext(**base)


# --- Одно действие, а не список проблем ------------------------------------

def test_only_one_thing_is_suggested_at_a_time():
    """Пять недоборов сразу — это ноль недоборов: человек закроет приложение."""
    action = next_action(day(water_ml=0, protein_g=10, fiber_g=0,
                             meals_logged=0, workouts_today=0, checkin_done=False))
    assert isinstance(action, Action)


def test_nothing_is_suggested_when_the_day_is_fine():
    """Выдуманный совет хуже тишины."""
    assert next_action(day()) is None


def test_night_is_left_alone():
    """В три часа ночи полезнее спать, чем добирать клетчатку."""
    for hour in (23, 2, 6):
        assert next_action(day(hour=hour, water_ml=0, meals_logged=0)) is None


# --- Приоритет -------------------------------------------------------------

def test_an_empty_diary_outweighs_everything():
    action = next_action(day(meals_logged=0, water_ml=1000, hour=13))
    assert action.code == "meal"


def test_water_comes_before_fiber_when_both_are_behind():
    """Стакан воды человек сделает прямо сейчас, а за клетчаткой надо идти."""
    action = next_action(day(water_ml=0, fiber_g=0, hour=15))
    assert action.code == "water"


def test_a_tired_person_is_not_pushed_into_a_workout():
    """Предлагать тренировку на пустой батарейке — это давление, а не забота."""
    tired = day(workouts_today=0, energy=1, water_ml=2100, hour=19)
    assert next_action(tired).code == "rest"
    assert "пройтись" in next_action(tired).text


def test_high_stress_is_treated_the_same_way():
    stressed = day(workouts_today=0, stress="high", water_ml=2100, hour=18)
    assert next_action(stressed).code == "rest"


def test_a_rested_person_gets_the_workout_offer():
    fresh = day(workouts_today=0, energy=5, water_ml=2100, hour=18)
    assert next_action(fresh).code == "movement"


# --- Не повторяться --------------------------------------------------------

def test_the_same_advice_is_not_repeated_all_day():
    """Совет, показанный трижды, перестают читать вместе со всей карточкой."""
    behind = dict(water_ml=0, hour=12)
    assert next_action(day(**behind)).code == "water"

    seen_twice = day(**behind, already_suggested=("water", "water"))
    action = next_action(seen_twice)
    assert action is None or action.code != "water"


def test_advice_stays_put_while_it_is_on_screen():
    """Карточка, меняющаяся при каждом обновлении, сбивает с толку.

    Пока человек не сделал по совету шаг, совет остаётся тем же.
    """
    ctx = day(water_ml=0, fiber_g=0, hour=15, already_suggested=("water",))
    assert next_action(ctx).code == "water"


def test_advice_shown_twice_yields_to_a_fresh_one():
    ctx = day(water_ml=0, fiber_g=0, hour=15,
              already_suggested=("water", "fiber", "water"))
    action = next_action(ctx)
    assert action is None or action.code != "water"


# --- Работаем на том, что есть --------------------------------------------

def test_a_missing_target_is_simply_not_discussed():
    """Нет нормы — нет совета. «Заполни профиль» здесь не ответ."""
    ctx = DayContext(hour=14, water_target=None, protein_target=None,
                     fiber_target=None, calories_target=None,
                     meals_logged=3, workouts_today=1, checkin_done=True,
                     days_since_measure=1)
    action = next_action(ctx)
    assert action is None or action.code not in {"water", "protein", "fiber"}


def test_an_empty_day_does_not_crash_the_engine():
    assert next_action(DayContext(hour=3)) is None
    assert isinstance(next_action(DayContext(hour=12)), (Action, type(None)))


@pytest.mark.parametrize("hour", range(24))
def test_every_hour_is_survivable(hour):
    """Движок не должен падать ни в какой час и ни на каких данных."""
    action = next_action(day(hour=hour, water_ml=0, protein_g=0, fiber_g=0,
                             meals_logged=0, workouts_today=0,
                             checkin_done=False, days_since_measure=30))
    assert action is None or action.cta


# --- Главные задания -------------------------------------------------------

QUESTS = [
    {"code": "meals", "done": True, "share": 1.0},
    {"code": "water", "done": False, "share": 0.2},
    {"code": "fiber", "done": False, "share": 0.9},
    {"code": "move", "done": False, "share": 0.0},
    {"code": "measure", "done": False, "share": 0.0},
    {"code": "stress", "done": True, "share": 1.0},
]


def test_only_three_quests_are_main():
    assert len(main_quest_codes(day(), QUESTS)) == 3


def test_finished_quests_do_not_occupy_the_top():
    codes = main_quest_codes(day(), QUESTS)
    assert "meals" not in codes and "stress" not in codes


def test_what_is_almost_done_is_shown_first():
    """Задание, до которого один шаг, важнее того, что не начато."""
    codes = main_quest_codes(day(), QUESTS)
    assert codes.index("fiber") < codes.index("move")


def test_the_quest_we_are_nudging_about_is_pulled_up():
    codes = main_quest_codes(day(water_ml=0, hour=12), QUESTS)
    assert codes[0] == "water"
