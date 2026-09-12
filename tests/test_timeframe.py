"""Тесты границ суток по часовому поясу пользователя."""

from datetime import datetime, timezone

from utils.timeframe import day_bounds, get_zone, today_in


def test_moscow_evening_is_already_next_day_in_utc_terms():
    # 3 сентября 23:30 в Москве — это 20:30 UTC того же дня.
    moment = datetime(2026, 9, 3, 20, 30, tzinfo=timezone.utc)
    assert today_in("Europe/Moscow", now=moment).isoformat() == "2026-09-03"


def test_after_midnight_local_is_new_day():
    # 00:30 по Москве = 21:30 UTC предыдущего дня, но для человека это уже 4-е.
    moment = datetime(2026, 9, 3, 21, 30, tzinfo=timezone.utc)
    assert today_in("Europe/Moscow", now=moment).isoformat() == "2026-09-04"


def test_day_bounds_cover_exactly_24_hours():
    start, end = day_bounds("Europe/Moscow", now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc))
    assert (end - start).total_seconds() == 24 * 3600


def test_day_bounds_are_returned_in_utc_but_start_at_local_midnight():
    """Наружу отдаём UTC (для запросов к БД), но это ровно местная полночь."""
    from zoneinfo import ZoneInfo

    start, _ = day_bounds("Europe/Moscow", now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc))
    assert start.tzinfo == timezone.utc
    local_start = start.astimezone(ZoneInfo("Europe/Moscow"))
    assert local_start.hour == 0 and local_start.minute == 0


def test_unknown_timezone_falls_back_to_moscow():
    assert str(get_zone("Планета/Марс")) == "Europe/Moscow"
    assert str(get_zone(None)) == "Europe/Moscow"


def test_different_timezones_give_different_days():
    moment = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)
    assert today_in("Europe/Moscow", now=moment).isoformat() == "2026-09-04"   # 01:00
    assert today_in("Europe/Lisbon", now=moment).isoformat() == "2026-09-03"   # 23:00


def test_known_zone_accepts_real_zones_and_rejects_junk():
    """get_zone молча подставляет Москву на любую чушь — для пояса,
    который приходит снаружи и сохраняется, нужна строгая проверка."""
    from utils.timeframe import is_known_zone

    assert is_known_zone("Asia/Vladivostok")
    assert is_known_zone("Europe/Moscow")
    assert not is_known_zone("Марс/Олимп")
    assert not is_known_zone("")
    assert not is_known_zone(None)
    assert not is_known_zone("A" * 200)
