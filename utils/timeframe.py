"""Границы суток в часовом поясе пользователя.

Дневник, напоминания и отметки о приёме препаратов должны считать «сегодня»
по местному времени человека, а не по UTC: иначе в Москве день кончается в
три часа ночи, а в Новосибирске — в семь утра.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Moscow"


def get_zone(timezone_name: str | None) -> ZoneInfo:
    """Часовой пояс пользователя; при неизвестном значении — московский."""
    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def today_in(timezone_name: str | None, *, now: datetime | None = None) -> date:
    """Какое сегодня число у пользователя."""
    zone = get_zone(timezone_name)
    moment = now.astimezone(zone) if now else datetime.now(zone)
    return moment.date()


def to_local(moment: datetime, timezone_name: str | None) -> datetime:
    """Момент из базы — в местное время пользователя.

    Часть драйверов (SQLite) возвращает время без зоны. Такое значение
    всегда хранится в UTC, поэтому и трактуем его как UTC: иначе время
    события уезжало бы на несколько часов.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(get_zone(timezone_name))


def day_bounds(
    timezone_name: str | None, *, day: date | None = None, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Начало и конец суток пользователя — как моменты времени с зоной.

    Возвращает полуинтервал [начало, конец): именно так их удобно
    подставлять в запросы к БД.
    """
    zone = get_zone(timezone_name)
    target = day or today_in(timezone_name, now=now)
    start = datetime.combine(target, time.min, tzinfo=zone)
    # Приводим к UTC: моменты те же, но сравнение с сохранённым временем
    # становится однозначным на любой СУБД.
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
