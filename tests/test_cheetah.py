"""Гепард: настроение приложения, а не второй советчик.

Главное, что здесь проверяется, — тон. Персонаж, который упрекает за
пропуски, работает против приложения: человек, которому стыдно открывать
дневник, его не открывает.
"""

import pytest

from utils import cheetah
from utils.cheetah import mood


def test_a_returning_person_is_met_not_scolded():
    """Здесь человека легче всего потерять окончательно."""
    result = mood(hour=12, days_away=9)
    assert result.code == cheetah.RETURNING
    assert "дождался" in result.line


@pytest.mark.parametrize("state", [
    dict(hour=12, days_away=30),
    dict(hour=12, days_away=3, streak=0),
    dict(hour=9, water_share=0.0),
    dict(hour=21, quests_done=0, quests_total=7),
    dict(hour=2, energy=1),
])
def test_the_cheetah_never_shames(state):
    line = mood(**state).line.lower()
    for shame in ("потерял", "пропустил", "не смог", "провал", "опять",
                  "снова не", "должна", "стыдно"):
        assert shame not in line, f"упрёк в реплике: {line}"


# --- Приоритет состояний ---------------------------------------------------

def test_a_new_place_beats_everything():
    assert mood(hour=3, energy=1, days_away=10, world_unlock=True).code == \
        cheetah.WORLD_UNLOCK


def test_an_award_beats_the_ordinary_day():
    assert mood(hour=14, new_awards=1, water_share=0.0).code == cheetah.CELEBRATION


def test_returning_matters_more_than_a_streak():
    """Вернувшегося встречаем, а не отчитываемся ему о цифрах."""
    assert mood(hour=12, days_away=5, streak=10, quests_done=1).code == \
        cheetah.RETURNING


def test_tiredness_outranks_thirst():
    """Уставшему не намекают на воду — ему дают выдохнуть."""
    assert mood(hour=15, energy=1, water_share=0.0).code == cheetah.SLEEPY
    assert mood(hour=15, stress="high", water_share=0.0).code == cheetah.SLEEPY


def test_night_is_always_quiet():
    for hour in (23, 0, 3, 5):
        assert mood(hour=hour, water_share=0.0, energy=5).code == cheetah.SLEEPY


# --- Обычный день ----------------------------------------------------------

@pytest.mark.parametrize("hour,expected", [
    (7, cheetah.MORNING), (9, cheetah.MORNING),
    (13, cheetah.IDLE), (16, cheetah.IDLE),
    (19, cheetah.EVENING), (21, cheetah.EVENING),
])
def test_the_day_has_its_own_rhythm(hour, expected):
    assert mood(hour=hour).code == expected


def test_a_workout_is_noticed():
    assert mood(hour=19, workouts_today=1).code == cheetah.ACTIVE


def test_a_finished_day_lets_you_exhale():
    result = mood(hour=20, quests_done=7, quests_total=7)
    assert result.code == cheetah.PROUD
    assert "выдохнуть" in result.line


def test_a_long_streak_is_named_by_its_number():
    result = mood(hour=12, streak=12, quests_done=2, quests_total=7)
    assert result.code == cheetah.STREAK
    assert "12" in result.line


def test_every_state_has_a_face_and_a_phrase():
    """Пустая реплика хуже отсутствующей: строка на экране должна что-то значить."""
    seen = set()
    for state in (dict(hour=8), dict(hour=13), dict(hour=20), dict(hour=2),
                  dict(hour=14, energy=5), dict(hour=14, water_share=0.0),
                  dict(hour=19, workouts_today=1),
                  dict(hour=20, quests_done=7, quests_total=7),
                  dict(hour=12, streak=9, quests_done=1),
                  dict(hour=12, days_away=4), dict(hour=12, new_awards=1),
                  dict(hour=12, world_unlock=True)):
        result = mood(**state)
        assert result.emoji and len(result.line) > 10
        seen.add(result.code)
    # Все двенадцать состояний из задания достижимы, а не написаны для вида.
    assert len(seen) == 12
