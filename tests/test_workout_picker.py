"""Подбор занятия: два вопроса вместо каталога из тринадцати программ."""

import pytest

from seed.workout_programs import PROGRAMS
from services.workout_picker import (CALM_STYLES, QUICK_LIMIT_MIN, pick,
                                     program_minutes, quick_five)


# --- Длительность ----------------------------------------------------------

@pytest.mark.parametrize("code", list(PROGRAMS))
def test_every_programme_has_a_believable_length(code):
    """Программа без длительности не подберётся ни под какое время."""
    minutes = program_minutes(code)
    assert 3 <= minutes <= 90, f"{PROGRAMS[code]['title']}: {minutes} мин"


# --- Подбор ----------------------------------------------------------------

def test_nothing_longer_than_the_time_available():
    """Предложить часовое занятие тому, у кого десять минут, — это обман."""
    for minutes in (10, 15, 20, 30, 45):
        for item in pick(minutes_available=minutes):
            assert item.minutes <= minutes * 1.15, \
                f"{item.title}: {item.minutes} мин при доступных {minutes}"


def test_a_tired_person_is_offered_something_calm():
    """Мало сил — не повод не двигаться, но повод не поднимать тяжёлое."""
    for item in pick(minutes_available=30, energy=1)[:1]:
        calm = item.style in CALM_STYLES or item.category != "body"
        assert calm, f"уставшему предложено: {item.title} ({item.style})"


def test_a_rested_person_gets_a_real_workout():
    top = pick(minutes_available=45, energy=5)[0]
    assert top.category == "body"


def test_yesterdays_workout_is_not_the_find_of_the_day():
    fresh = pick(minutes_available=45, energy=5)[0]
    other = pick(minutes_available=45, energy=5, recent=(fresh.code,))[0]
    assert other.code != fresh.code


def test_place_is_respected():
    for item in pick(minutes_available=45, location="home"):
        assert item.location == "home"


def test_every_pick_explains_itself():
    for item in pick(minutes_available=20):
        assert item.why and item.minutes > 0


def test_an_impossible_request_returns_nothing_rather_than_a_lie():
    """Двухминутной программы нет — и придумывать её не надо."""
    assert pick(minutes_available=2) == []


# --- «У меня 5 минут» ------------------------------------------------------

def test_five_minutes_really_means_five():
    sets = quick_five()
    assert sets, "быстрый режим не собрался"
    for item in sets:
        assert item.minutes <= QUICK_LIMIT_MIN + 1, f"{item.title}: {item.minutes} мин"


def test_a_quick_set_is_made_of_real_exercises():
    """Берём начало существующей программы, а не выдумываем упражнения."""
    known = {name for program in PROGRAMS.values()
             for name, *_ in program["exercises"]}
    for item in quick_five():
        assert len(item.exercises) >= 2
        for name in item.exercises:
            assert name in known, f"выдуманное упражнение: {name}"


def test_a_quick_set_points_at_the_programme_it_came_from():
    for item in quick_five():
        assert item.code in PROGRAMS
        assert PROGRAMS[item.code]["title"] in item.why


def test_quick_sets_cover_different_things():
    codes = {item.code for item in quick_five()}
    assert len(codes) >= 3, "быстрый режим предлагает одно и то же"
