"""Тесты расписания приёма препаратов."""

from datetime import date

import pytest

from models import ScheduleTypeEnum
from utils.schedules import describe, format_weekdays, is_due, parse_weekdays

START = date(2026, 9, 7)  # понедельник


def test_daily_is_due_every_day():
    for offset in range(10):
        assert is_due(
            schedule_type=ScheduleTypeEnum.DAILY,
            on_date=date.fromordinal(START.toordinal() + offset),
            start_date=START,
        )


def test_weekdays_only_on_selected_days():
    # понедельник, среда, пятница
    kwargs = dict(schedule_type=ScheduleTypeEnum.WEEKDAYS, start_date=START, weekdays="0,2,4")
    assert is_due(on_date=date(2026, 9, 7), **kwargs)       # пн
    assert not is_due(on_date=date(2026, 9, 8), **kwargs)   # вт
    assert is_due(on_date=date(2026, 9, 9), **kwargs)       # ср
    assert is_due(on_date=date(2026, 9, 11), **kwargs)      # пт
    assert not is_due(on_date=date(2026, 9, 12), **kwargs)  # сб


def test_weekly_interval_repeats_every_seven_days():
    kwargs = dict(schedule_type=ScheduleTypeEnum.INTERVAL, start_date=START, interval_days=7)
    assert is_due(on_date=START, **kwargs)
    assert not is_due(on_date=date(2026, 9, 10), **kwargs)
    assert is_due(on_date=date(2026, 9, 14), **kwargs)
    assert is_due(on_date=date(2026, 9, 21), **kwargs)


def test_nothing_is_due_before_start():
    assert not is_due(
        schedule_type=ScheduleTypeEnum.DAILY, on_date=date(2026, 9, 6), start_date=START
    )


def test_interval_without_value_is_not_due():
    assert not is_due(
        schedule_type=ScheduleTypeEnum.INTERVAL, on_date=START, start_date=START, interval_days=None
    )


@pytest.mark.parametrize(
    "raw,expected",
    [("0,2,4", {0, 2, 4}), (" 1 , 3 ", {1, 3}), ("", set()), (None, set()), ("9,abc,2", {2})],
)
def test_parse_weekdays(raw, expected):
    assert parse_weekdays(raw) == expected


def test_format_weekdays_is_human_readable():
    assert format_weekdays({0, 2, 4}) == "пн, ср, пт"
    assert format_weekdays(set()) == ""


def test_describe_covers_all_modes():
    assert describe(schedule_type=ScheduleTypeEnum.DAILY) == "каждый день"
    assert describe(schedule_type=ScheduleTypeEnum.WEEKDAYS, weekdays="0,4") == "по дням: пн, пт"
    assert describe(schedule_type=ScheduleTypeEnum.INTERVAL, interval_days=7) == "раз в неделю"
    assert describe(schedule_type=ScheduleTypeEnum.INTERVAL, interval_days=10) == "раз в 10 дн."
