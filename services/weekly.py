"""Итоги недели: раз в неделю показать человеку его же неделю целиком.

День за днём видно только сегодня, и из-за этого теряется главное — что за
неделю набралось. Пять дней дневника и минус полкило выглядят иначе, чем
четверг, в который «опять не влезла в норму».

Тон тот же, что в фразе дня: считаем факты и не выносим приговор. Неделя без
записей — не провал и не повод для выговора, а вес, который вырос, — не
приговор: цифра на весах гуляет от воды, соли и цикла, и человеку полезнее об
этом знать, чем чувствовать себя виноватым.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import BodyMeasurement, Meal, User, WaterLog, WorkoutLog
from utils.timeframe import day_bounds, to_local

# Воскресенье (0 — понедельник) и ранний вечер: неделя уже закончилась, но
# человек ещё не спит и успевает что-то решить про следующую.
SUMMARY_WEEKDAY = 6
SUMMARY_TIME = time(19, 0)

# Окно итогов: сегодня и шесть предыдущих дней.
WINDOW_DAYS = 7

# Меньше этого разница на весах — не изменение, а колебание воды.
WEIGHT_NOISE_KG = 0.2


@dataclass(frozen=True)
class WeeklySummary:
    """Неделя человека в цифрах, без выводов — выводы делает render()."""

    user_id: int
    days_logged: int
    avg_calories: int
    norm_calories: int | None
    weight_from: float | None
    weight_to: float | None
    workouts: int
    water_days: int

    @property
    def weight_change(self) -> float | None:
        if self.weight_from is None or self.weight_to is None:
            return None
        return round(self.weight_to - self.weight_from, 1)

    @property
    def is_empty(self) -> bool:
        """Пустая неделя: писать в такую не о чем."""
        return not (self.days_logged or self.workouts or self.water_days)


async def build_summary(
    session: AsyncSession, user: User, *, today: date | None = None
) -> WeeklySummary:
    """Собрать неделю по местным суткам человека."""
    last_day = today or to_local(datetime.now(timezone.utc), user.timezone).date()
    start, _ = day_bounds(user.timezone, day=last_day - timedelta(days=WINDOW_DAYS - 1))
    _, end = day_bounds(user.timezone, day=last_day)

    meals = (
        await session.execute(
            select(Meal).where(
                Meal.user_id == user.id, Meal.logged_at >= start, Meal.logged_at < end
            )
        )
    ).scalars().all()

    by_day: dict[date, float] = {}
    for meal in meals:
        day = to_local(meal.logged_at, user.timezone).date()
        by_day[day] = by_day.get(day, 0.0) + float(meal.calories or 0)

    # Среднее — только по дням, когда человек писал. Иначе пропущенный день
    # выглядит как день голодания и занижает среднее до неправды.
    days_logged = len(by_day)
    avg = round(sum(by_day.values()) / days_logged) if days_logged else 0

    weights = (
        await session.execute(
            select(BodyMeasurement)
            .where(
                BodyMeasurement.user_id == user.id,
                BodyMeasurement.measured_at >= start,
                BodyMeasurement.measured_at < end,
                BodyMeasurement.weight_kg.is_not(None),
            )
            .order_by(BodyMeasurement.measured_at)
        )
    ).scalars().all()
    # Одно взвешивание за неделю ничего не сравнивает — это не динамика.
    weight_from = float(weights[0].weight_kg) if len(weights) >= 2 else None
    weight_to = float(weights[-1].weight_kg) if len(weights) >= 2 else None

    workouts = len(
        (
            await session.execute(
                select(WorkoutLog.id).where(
                    WorkoutLog.user_id == user.id,
                    WorkoutLog.completed_at >= start,
                    WorkoutLog.completed_at < end,
                )
            )
        ).all()
    )

    water_rows = (
        await session.execute(
            select(WaterLog.logged_at).where(
                WaterLog.user_id == user.id,
                WaterLog.logged_at >= start,
                WaterLog.logged_at < end,
            )
        )
    ).scalars().all()
    water_days = len({to_local(moment, user.timezone).date() for moment in water_rows})

    return WeeklySummary(
        user_id=user.id,
        days_logged=days_logged,
        avg_calories=avg,
        norm_calories=user.daily_calories,
        weight_from=weight_from,
        weight_to=weight_to,
        workouts=workouts,
        water_days=water_days,
    )


def _weight_line(summary: WeeklySummary, goal: str | None) -> str | None:
    change = summary.weight_change
    if change is None:
        return None

    line = f"⚖️ Вес: {summary.weight_from:.1f} → {summary.weight_to:.1f} кг"
    if abs(change) < WEIGHT_NOISE_KG:
        return f"{line} (почти без изменений — это тоже нормальная неделя)"

    sign = "−" if change < 0 else "+"
    line = f"{line} ({sign}{abs(change):.1f})"

    # Движение «не в ту сторону» комментируем без вины: цифра на весах
    # зависит от воды и соли не меньше, чем от еды.
    wrong_way = (goal == "lose_weight" and change > 0) or (goal == "gain_mass" and change < 0)
    if wrong_way:
        return f"{line}\nВес гуляет от воды, соли и цикла — по одной неделе рано судить."
    return line


def render(summary: WeeklySummary, *, goal: str | None = None) -> str:
    """Текст воскресного сообщения."""
    if summary.days_logged == 0:
        return (
            "🗓 Итоги недели\n\n"
            "На этой неделе в дневнике пусто. Так бывает — неделя может быть "
            "просто не про подсчёты.\n\n"
            "Начать заново можно с одного приёма пищи, прямо сегодня."
        )

    lines = [
        "🗓 Итоги недели",
        "",
        f"📔 Дневник: {summary.days_logged} из {WINDOW_DAYS} дней",
    ]

    average = f"🍽 В среднем: {summary.avg_calories} ккал в день"
    if summary.norm_calories:
        average += f" (норма {summary.norm_calories})"
    lines.append(average)

    weight = _weight_line(summary, goal)
    if weight:
        lines.append(weight)
    if summary.workouts:
        lines.append(f"🏋️ Тренировок: {summary.workouts}")
    if summary.water_days:
        lines.append(f"💧 Вода отмечена: {summary.water_days} дн.")

    lines += ["", _closing(summary)]
    return "\n".join(lines)


def _closing(summary: WeeklySummary) -> str:
    """Последняя строка — то, ради чего это сообщение вообще читают."""
    if summary.days_logged >= WINDOW_DAYS:
        return ("Ты записывала каждый день. Это та самая скучная работа, "
                "из которой всё и складывается.")
    if summary.days_logged >= 4:
        return ("Больше половины недели с дневником — этого достаточно, "
                "чтобы видеть картину.")
    return ("Несколько дней — уже больше, чем ноль. Дневник не обязан быть "
            "идеальным, чтобы приносить пользу.")


async def users_for_summary(
    session: AsyncSession, *, now_utc: datetime | None = None
) -> list[User]:
    """Кому прямо сейчас (по их местному времени) пора показать неделю."""
    moment = now_utc or datetime.now(timezone.utc)
    users = (
        await session.execute(
            select(User).where(
                User.onboarding_completed.is_(True), User.reminders_enabled.is_(True)
            )
        )
    ).scalars().all()

    due = []
    for user in users:
        local_now = to_local(moment, user.timezone)
        if local_now.weekday() != SUMMARY_WEEKDAY:
            continue
        if (local_now.hour, local_now.minute) != (SUMMARY_TIME.hour, SUMMARY_TIME.minute):
            continue
        due.append(user)
    return due


__all__ = [
    "SUMMARY_TIME",
    "SUMMARY_WEEKDAY",
    "WINDOW_DAYS",
    "WeeklySummary",
    "build_summary",
    "render",
    "users_for_summary",
]
