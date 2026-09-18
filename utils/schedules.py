"""Расписание приёма препаратов: положен ли он в конкретный день.

Три режима покрывают почти все реальные схемы:
- каждый день (витамин D, магний);
- по дням недели («пн, ср, пт» — например, железо через день);
- раз в N дней (укол раз в неделю, витамин B12 раз в 10 дней).
"""

from __future__ import annotations

from datetime import date

from models import ScheduleTypeEnum

WEEKDAY_NAMES_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def parse_weekdays(raw: str | None) -> set[int]:
    """«0,2,4» → {0, 2, 4}. Мусор и пустые значения игнорируются."""
    if not raw:
        return set()
    days = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 6:
            days.add(int(part))
    return days


def format_weekdays(days: set[int] | None) -> str:
    """{0, 2, 4} → «пн, ср, пт» — для показа пользователю."""
    if not days:
        return ""
    return ", ".join(WEEKDAY_NAMES_RU[d] for d in sorted(days))


def is_due(
    *,
    schedule_type: ScheduleTypeEnum,
    on_date: date,
    start_date: date,
    weekdays: str | None = None,
    interval_days: int | None = None,
) -> bool:
    """Нужно ли принимать препарат в день `on_date`.

    `start_date` — день, с которого ведётся приём (для режима «раз в N дней»
    именно от него отсчитываются интервалы).
    """
    if on_date < start_date:
        return False

    if schedule_type == ScheduleTypeEnum.DAILY:
        return True

    if schedule_type == ScheduleTypeEnum.WEEKDAYS:
        return on_date.weekday() in parse_weekdays(weekdays)

    if schedule_type == ScheduleTypeEnum.INTERVAL:
        if not interval_days or interval_days < 1:
            return False
        return (on_date - start_date).days % interval_days == 0

    return False


def describe(
    *,
    schedule_type: ScheduleTypeEnum,
    weekdays: str | None = None,
    interval_days: int | None = None,
) -> str:
    """Человеческое описание расписания для карточки препарата."""
    if schedule_type == ScheduleTypeEnum.DAILY:
        return "каждый день"
    if schedule_type == ScheduleTypeEnum.WEEKDAYS:
        days = format_weekdays(parse_weekdays(weekdays))
        return f"по дням: {days}" if days else "дни не выбраны"
    if schedule_type == ScheduleTypeEnum.INTERVAL:
        if interval_days == 7:
            return "раз в неделю"
        if interval_days == 1:
            return "каждый день"
        return f"раз в {interval_days} дн." if interval_days else "интервал не задан"
    return "не задано"
