"""Шаги: сколько прошёл, какая цель, серия и рейтинг.

Одно ограничение честнее назвать вслух. Мини-приложение внутри Telegram не
умеет читать шаги само: доступа ни к «Здоровью» на айфоне, ни к датчику у
него нет — это может только отдельное приложение из магазина. Значит, число
вносит человек, глядя в телефон.

Из этого следует всё остальное устройство рейтинга. Соревнование на числах,
которые люди вписывают сами, — это соревнование в честности, и защищать его
запретами бессмысленно. Поэтому здесь не запреты, а потолок: в рейтинг идёт
не больше RANKED_CAP шагов за день. Приписка перестаёт окупаться — выше
потолка она просто не считается, а до потолка её проще пройти ногами.

И второе: цель по шагам человек назначает себе сам. В отличие от калорий,
это не медицинская норма, а договорённость с собой, и подставлять сюда
чужое число нельзя.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ActivityLevelEnum, StepLog, User
from utils.timeframe import DEFAULT_TIMEZONE, today_in

# Готовые варианты цели. Десять тысяч — не медицинская норма, а привычное
# круглое число; предлагаем и меньше, чтобы цель можно было выполнить.
GOAL_CHOICES = (5000, 7000, 10000, 12000)
MIN_GOAL = 1000
MAX_GOAL = 30000

# Что подставляем тому, кто цель ещё не выбирал: по уровню активности.
GOAL_BY_ACTIVITY = {
    ActivityLevelEnum.SEDENTARY: 6000,
    ActivityLevelEnum.LIGHT: 8000,
    ActivityLevelEnum.MODERATE: 10000,
    ActivityLevelEnum.HIGH: 12000,
    ActivityLevelEnum.VERY_HIGH: 12000,
}
DEFAULT_GOAL = 8000

# Больше этого за сутки человек не проходит: полсотни километров пешком —
# это уже суточный переход, а не день с телефоном в кармане. Число выше
# почти всегда опечатка, и хранить её незачем.
MAX_DAILY = 60000

# А в рейтинг идёт и того меньше. Приписывать смысла нет: выше потолка
# лишнее не считается, а до потолка проще дойти ногами.
RANKED_CAP = 30000

# Неделя календарная, с понедельника по воскресенье, а не скользящие семь
# дней. Соревнование без общей границы закрыть нечем: у каждого своя «неделя»,
# и объявить итог в понедельник было бы враньём.
WEEK_DAYS = 7


def week_bounds(day: date) -> tuple[date, date]:
    """Понедельник и воскресенье той недели, в которой этот день."""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def last_week_bounds(day: date) -> tuple[date, date]:
    """Границы предыдущей недели — той, итог которой объявляют."""
    start, _ = week_bounds(day)
    return start - timedelta(days=WEEK_DAYS), start - timedelta(days=1)


def goal_for(user: User) -> int:
    """Цель человека. Своя, если выбрал; иначе разумная по активности."""
    if user.daily_steps:
        return max(MIN_GOAL, min(int(user.daily_steps), MAX_GOAL))
    return GOAL_BY_ACTIVITY.get(user.activity_level, DEFAULT_GOAL)


def clean_goal(value) -> int | None:
    """Проверить цель, введённую человеком. None — если это не число."""
    try:
        number = int(float(str(value).replace(",", ".").replace(" ", "")))
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return max(MIN_GOAL, min(number, MAX_GOAL))


def clean_steps(value) -> int | None:
    """Проверить число шагов. None — если это вообще не число."""
    try:
        number = int(float(str(value).replace(",", ".").replace(" ", "")))
    except (TypeError, ValueError):
        return None
    return max(0, min(number, MAX_DAILY))


@dataclass(frozen=True)
class Steps:
    """Шаги человека на сегодня и вокруг."""

    today: int
    goal: int
    week: int
    streak: int
    total: int
    best: int

    @property
    def done(self) -> bool:
        return bool(self.goal) and self.today >= self.goal

    @property
    def share(self) -> float:
        return min(self.today / self.goal, 1.0) if self.goal else 0.0

    @property
    def left(self) -> int:
        return max(self.goal - self.today, 0)

    def to_dict(self) -> dict:
        return {"today": self.today, "goal": self.goal, "week": self.week,
                "streak": self.streak, "total": self.total, "best": self.best,
                "done": self.done, "left": self.left,
                "share": round(self.share, 3)}


async def record(session: AsyncSession, user_id: int, steps: int, *,
                 day: date | None = None,
                 timezone_name: str = DEFAULT_TIMEZONE) -> int:
    """Записать шаги за день. Повторная запись уточняет число, а не прибавляет.

    Телефон показывает итог с начала суток, поэтому складывать записи было бы
    неверно: человек, заглянувший в приложение трижды, получил бы тройной день.
    """
    value = clean_steps(steps)
    if value is None:
        raise ValueError("Это не похоже на число шагов")

    when = day or today_in(timezone_name)
    row = (await session.execute(
        select(StepLog).where(StepLog.user_id == user_id, StepLog.day == when)
    )).scalar_one_or_none()

    if row is None:
        session.add(StepLog(user_id=user_id, day=when, steps=value, source="manual"))
    else:
        row.steps = value
    await session.commit()
    return value


async def on_day(session: AsyncSession, user_id: int, day: date) -> int:
    return int((await session.execute(
        select(func.coalesce(func.sum(StepLog.steps), 0))
        .where(StepLog.user_id == user_id, StepLog.day == day)
    )).scalar_one() or 0)


async def history(session: AsyncSession, user_id: int, *, days: int = 7,
                  timezone_name: str = DEFAULT_TIMEZONE,
                  today: date | None = None) -> dict[date, int]:
    """Шаги по дням за последние `days` суток, включая сегодня."""
    end = today or today_in(timezone_name)
    start = end - timedelta(days=days - 1)
    rows = (await session.execute(
        select(StepLog.day, StepLog.steps).where(
            StepLog.user_id == user_id, StepLog.day >= start, StepLog.day <= end)
    )).all()
    return {day: int(steps or 0) for day, steps in rows}


async def streak(session: AsyncSession, user_id: int, goal: int, *,
                 timezone_name: str = DEFAULT_TIMEZONE,
                 today: date | None = None) -> int:
    """Сколько дней подряд человек добирает цель.

    Сегодняшний день не обрывает серию: он ещё не кончился, и обнулять
    счётчик в полдень было бы наказанием за то, что человек зашёл в
    приложение.
    """
    if goal <= 0:
        return 0
    end = today or today_in(timezone_name)
    by_day = await history(session, user_id, days=400, timezone_name=timezone_name,
                           today=end)

    count = 0
    day = end
    if by_day.get(end, 0) >= goal:
        count, day = 1, end - timedelta(days=1)
    else:
        day = end - timedelta(days=1)

    while by_day.get(day, 0) >= goal:
        count += 1
        day -= timedelta(days=1)
    return count


async def totals(session: AsyncSession, user_id: int) -> tuple[int, int, int]:
    """Всего шагов, лучший день и сколько дней вообще записано."""
    row = (await session.execute(
        select(func.coalesce(func.sum(StepLog.steps), 0),
               func.coalesce(func.max(StepLog.steps), 0),
               func.count(StepLog.id))
        .where(StepLog.user_id == user_id)
    )).one()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


async def state(session: AsyncSession, user: User, *,
                timezone_name: str = DEFAULT_TIMEZONE,
                today: date | None = None) -> Steps:
    """Всё про шаги человека одним ответом."""
    today = today or today_in(timezone_name)
    goal = goal_for(user)
    start, _ = week_bounds(today)
    by_day = await history(session, user.id, days=(today - start).days + 1,
                           timezone_name=timezone_name, today=today)
    total, best, _ = await totals(session, user.id)

    return Steps(
        today=by_day.get(today, 0),
        goal=goal,
        week=sum(by_day.values()),
        streak=await streak(session, user.id, goal, timezone_name=timezone_name,
                            today=today),
        total=total,
        best=best,
    )


# --- Рейтинг ---------------------------------------------------------------

@dataclass(frozen=True)
class Row:
    """Строка таблицы: человек и его неделя."""

    user_id: int
    name: str
    steps: int
    days: int      # в скольких днях недели он добрал свою цель
    is_me: bool = False

    def to_dict(self) -> dict:
        return {"user_id": self.user_id, "name": self.name, "steps": self.steps,
                "days": self.days, "me": self.is_me}


def _first_name(user: User) -> str:
    """В таблице показываем имя, а не полное имя с фамилией."""
    return (user.full_name or "").strip().split(" ")[0] or "без имени"


async def week_rows(session: AsyncSession, user_ids, *, me: int | None = None,
                    timezone_name: str = DEFAULT_TIMEZONE,
                    today: date | None = None,
                    period: tuple[date, date] | None = None) -> list[Row]:
    """Недельная таблица по списку людей, от большего к меньшему.

    Каждый день учитывается не больше, чем RANKED_CAP: приписка выше потолка
    ничего не даёт, и рейтинг остаётся про ходьбу, а не про фантазию.
    """
    ids = [int(user_id) for user_id in user_ids]
    if not ids:
        return []

    start, end = period or week_bounds(today or today_in(timezone_name))

    rows = (await session.execute(
        select(StepLog.user_id, StepLog.day, StepLog.steps).where(
            StepLog.user_id.in_(ids), StepLog.day >= start, StepLog.day <= end)
    )).all()

    users = {user.id: user for user in (await session.execute(
        select(User).where(User.id.in_(ids))
    )).scalars()}

    walked: dict[int, int] = {}
    days_done: dict[int, int] = {}
    for user_id, _, steps in rows:
        user = users.get(int(user_id))
        if user is None:
            continue
        counted = min(int(steps or 0), RANKED_CAP)
        walked[int(user_id)] = walked.get(int(user_id), 0) + counted
        if counted >= goal_for(user):
            days_done[int(user_id)] = days_done.get(int(user_id), 0) + 1

    board = [
        Row(user_id=user_id, name=_first_name(user), steps=walked.get(user_id, 0),
            days=days_done.get(user_id, 0), is_me=user_id == me)
        for user_id, user in users.items()
    ]
    board.sort(key=lambda row: (-row.steps, row.name))
    return board


async def global_top(session: AsyncSession, *, limit: int = 20,
                     me: int | None = None,
                     timezone_name: str = DEFAULT_TIMEZONE,
                     today: date | None = None,
                     period: tuple[date, date] | None = None) -> list[Row]:
    """Таблица по всему приложению за неделю.

    Берём только тех, кто на этой неделе что-то записал: список из сотни
    нулей никого не вдохновляет.
    """
    start, end = period or week_bounds(today or today_in(timezone_name))

    ids = (await session.execute(
        select(StepLog.user_id).where(StepLog.day >= start, StepLog.day <= end,
                                      StepLog.steps > 0).distinct()
    )).scalars().all()
    if me is not None and me not in ids:
        ids = list(ids) + [me]

    rows = await week_rows(session, ids, me=me, timezone_name=timezone_name,
                           period=(start, end))
    return rows[:limit]


def place_of(rows: list[Row], user_id: int) -> int | None:
    """Какое место занимает человек. None — если его нет в таблице."""
    for index, row in enumerate(rows, start=1):
        if row.user_id == user_id:
            return index
    return None


__all__ = ["DEFAULT_GOAL", "GOAL_BY_ACTIVITY", "GOAL_CHOICES", "MAX_DAILY", "MAX_GOAL",
           "MIN_GOAL", "RANKED_CAP", "WEEK_DAYS", "Row", "Steps", "clean_goal",
           "clean_steps", "global_top", "goal_for", "history", "last_week_bounds",
           "on_day", "place_of", "record", "state", "streak", "totals",
           "week_bounds", "week_rows"]
