"""Тесты фразы дня в шапке приложения."""

from datetime import date

import pytest

from models import GoalEnum
from utils.daily_line import CARE_LINES, DEFAULT_LINES, LINES, daily_line, pool_for

DAY = date(2026, 9, 5)


def test_same_line_all_day():
    """Если фраза меняется при каждом открытии, читать её перестают."""
    first = daily_line(goal="lose_weight", user_id=1, day=DAY)
    again = daily_line(goal="lose_weight", user_id=1, day=DAY)
    assert first == again


def test_line_changes_over_two_weeks():
    seen = {
        daily_line(goal="lose_weight", user_id=1, day=date(2026, 9, d))
        for d in range(1, 15)
    }
    assert len(seen) >= 6


def test_different_people_see_different_lines():
    """Иначе в один день у всех подписчиков одна и та же строка."""
    lines = {daily_line(goal="lose_weight", user_id=uid, day=DAY) for uid in range(40)}
    assert len(lines) > 3


@pytest.mark.parametrize("goal", [g.value for g in GoalEnum])
def test_every_goal_has_its_own_lines(goal):
    """Цель из анкеты без своих фраз молча свалилась бы в общие."""
    assert goal in LINES
    assert daily_line(goal=goal, user_id=7, day=DAY) in pool_for(goal)


def test_profile_without_a_goal_still_gets_a_line():
    assert daily_line(goal=None, user_id=7, day=DAY) in pool_for(None)
    assert daily_line(goal="", user_id=7, day=DAY) in pool_for(None)


def test_unknown_goal_does_not_break():
    assert daily_line(goal="что-то новое", user_id=7, day=DAY) in pool_for(None)


ALL_LINES = ([line for group in LINES.values() for line in group]
             + list(DEFAULT_LINES) + list(CARE_LINES))


def test_lines_fit_the_header():
    """Длинная фраза разъезжается на три строки и ломает шапку."""
    for line in ALL_LINES:
        assert len(line) <= 78, line


def test_lines_are_not_repeated():
    assert len(ALL_LINES) == len(set(ALL_LINES))


def test_lines_do_not_promise_and_do_not_diagnose():
    """Мотивация — не место для медицинских обещаний и сроков."""
    forbidden = ("гарант", "за неделю", "за месяц", "похудеешь на", "болезн", "лечен")
    for line in ALL_LINES:
        lowered = line.lower()
        for word in forbidden:
            assert word not in lowered, line


def test_support_lines_show_up_for_every_goal():
    """Ради них всё и делалось: поддержка должна доходить при любой цели."""
    for goal in [g.value for g in GoalEnum] + [None]:
        seen = {
            daily_line(goal=goal, user_id=uid, day=date(2026, 9, 5 + uid % 20))
            for uid in range(120)
        }
        assert seen & set(CARE_LINES), goal


def test_lines_never_scold():
    """Приложение — подруга, а не тренер: за срыв и пропуск не отчитываем."""
    scolding = ("должна", "обязана", "лень", "оправдани", "соберись", "не ной",
                "нельзя себе", "стыд", "вина", "провалила")
    for line in ALL_LINES:
        lowered = line.lower()
        for word in scolding:
            # «Усталость — это не лень» говорит ровно обратное, потому и живёт.
            if word == "лень" and "не лень" in lowered:
                continue
            assert word not in lowered, line


def test_no_exclamation_marks():
    """Восклицание в такой строке всегда звучит как подгоняющий тренер."""
    assert all("!" not in line for line in ALL_LINES)
