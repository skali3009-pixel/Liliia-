"""Тесты ленты дня и свёртки состояния (services/timeline.py, services/checkins.py)."""

from datetime import datetime, timedelta, timezone

from models import Checkin, WorkoutLog
from services.checkins import fold_state
from services.timeline import _group_workouts, _state_event


def moment(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 4, hour, minute, tzinfo=timezone.utc)


def checkin(**kwargs) -> Checkin:
    return Checkin(user_id=1, logged_at=kwargs.pop("at", moment(9)), **kwargs)


def test_state_event_reads_first_mentioned_value_as_title():
    event = _state_event(checkin(mood="спокойно", energy=7))
    assert event.title == "Настроение: спокойно"
    assert "энергия 7/10" in event.subtitle


def test_state_event_is_skipped_when_nothing_was_said():
    assert _state_event(checkin()) is None


def test_sleep_is_shown_in_hours_and_minutes():
    event = _state_event(checkin(sleep_minutes=452))
    assert "сон 7 ч 32 м" in event.title.lower()


def log(at: datetime, calories: float = 20, minutes: float = 5) -> WorkoutLog:
    return WorkoutLog(user_id=1, workout_id=1, completed_at=at,
                      calories_burned=calories, duration_minutes=minutes)


def test_exercises_of_one_session_collapse_into_a_single_event():
    events = _group_workouts([log(moment(18, 0)), log(moment(18, 12)), log(moment(18, 25))])
    assert len(events) == 1
    assert events[0].subtitle == "3 упражнений · 15 мин"
    assert events[0].value == "60 ккал"


def test_a_long_pause_starts_a_new_session():
    events = _group_workouts([log(moment(8, 0)), log(moment(19, 0))])
    assert len(events) == 2


def test_session_is_timed_by_its_first_exercise():
    events = _group_workouts([log(moment(18, 25)), log(moment(18, 0))])
    assert events[0].at == moment(18, 0)


def test_state_of_the_day_keeps_the_latest_value_of_each_field():
    """Утром сон, днём энергия — к вечеру видно и то, и другое."""
    state = fold_state([
        checkin(at=moment(8), sleep_minutes=450, energy=5),
        checkin(at=moment(14), energy=8),
        checkin(at=moment(20), mood="устала"),
    ])
    assert state.sleep_minutes == 450
    assert state.energy == 8
    assert state.mood == "устала"


def test_empty_day_has_empty_state():
    assert fold_state([]).is_empty
