"""Тесты: кому и когда напоминать о препарате."""

from datetime import date, datetime, time

import pytest

from models import ScheduleTypeEnum
from services.reminders import needs_reminder

START = date(2026, 9, 7)  # понедельник
BASE = dict(
    schedule_type=ScheduleTypeEnum.DAILY,
    start_date=START,
    weekdays=None,
    interval_days=None,
    already_logged=False,
)


def test_reminds_at_exact_minute():
    assert needs_reminder(
        reminder_time=time(9, 0), local_now=datetime(2026, 9, 8, 9, 0), **BASE
    )


def test_silent_at_other_minutes():
    for moment in [datetime(2026, 9, 8, 8, 59), datetime(2026, 9, 8, 9, 1),
                   datetime(2026, 9, 8, 21, 0)]:
        assert not needs_reminder(reminder_time=time(9, 0), local_now=moment, **BASE)


def test_no_reminder_without_time():
    assert not needs_reminder(
        reminder_time=None, local_now=datetime(2026, 9, 8, 9, 0), **BASE
    )


def test_no_reminder_if_already_taken():
    kwargs = {**BASE, "already_logged": True}
    assert not needs_reminder(
        reminder_time=time(9, 0), local_now=datetime(2026, 9, 8, 9, 0), **kwargs
    )


def test_weekly_supplement_reminds_only_on_its_day():
    kwargs = {**BASE, "schedule_type": ScheduleTypeEnum.INTERVAL, "interval_days": 7}
    assert needs_reminder(
        reminder_time=time(9, 0), local_now=datetime(2026, 9, 14, 9, 0), **kwargs
    )
    assert not needs_reminder(
        reminder_time=time(9, 0), local_now=datetime(2026, 9, 15, 9, 0), **kwargs
    )


def test_weekday_supplement_skips_wrong_days():
    kwargs = {**BASE, "schedule_type": ScheduleTypeEnum.WEEKDAYS, "weekdays": "0,2,4"}
    assert needs_reminder(  # среда
        reminder_time=time(20, 30), local_now=datetime(2026, 9, 9, 20, 30), **kwargs
    )
    assert not needs_reminder(  # четверг
        reminder_time=time(20, 30), local_now=datetime(2026, 9, 10, 20, 30), **kwargs
    )
