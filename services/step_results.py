"""Итог недели по шагам: то, ради чего в рейтинг возвращаются.

Таблица сама по себе не работает. Её видит только тот, кто сам зашёл
посмотреть, а заходить незачем: цифры те же, что вчера. Работает круг —
неделя началась, неделя закрылась, объявили результат, счёт с нуля.

Поэтому здесь одно сообщение в неделю, в понедельник утром. Правила те же,
что у остальных писем бота:

- только тем, кто на прошлой неделе действительно ходил. «Ты прошла 0 шагов,
  ты последняя» — это не итог, а пинок;
- прошлая неделя показывается числом, без слов «меньше» и «хуже»: человек
  сам умеет сравнивать два числа, а упрёк от приложения про еду и вес
  заканчивается тем, что приложение удаляют;
- кто выключил напоминания, не получает ничего.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from services import steps as step_service
from services import teams
from utils.plural import plural
from utils.timeframe import DEFAULT_TIMEZONE, matching_zones, today_in

logger = logging.getLogger(__name__)

# Понедельник, десять утра по местному времени. Не в воскресенье вечером:
# итог недели, пришедший, когда неделя ещё идёт, обесценивает последний день.
SEND_WEEKDAY = 0
SEND_AT = time(10, 0)


@dataclass(frozen=True)
class Result:
    """Чем закончилась неделя у одного человека."""

    user_id: int
    steps: int
    days_done: int
    goal: int
    previous: int
    place: int | None            # место по всему приложению
    people: int                  # сколько людей вообще ходило
    team_name: str = ""
    team_total: int = 0
    team_place: int | None = None
    team_people: int = 0

    @property
    def walked(self) -> bool:
        return self.steps > 0


def render(result: Result) -> str:
    """Сообщение с итогом. Числа, а не оценки."""
    lines = ["🏁 Неделя закрыта", ""]
    if result.days_done:
        days = plural(result.days_done, "день", "дня", "дней")
        lines.append(f"Ты прошла {result.steps} шагов, норму взяла "
                     f"{result.days_done} {days} из 7.")
    else:
        # Начинать итог с «ноль дней из семи» — значит открыть его упрёком.
        # А цель, которую не удалось взять ни разу, чаще великовата, чем
        # человек ленив: об этом полезнее сказать, чем о нуле.
        lines.append(f"Ты прошла {result.steps} шагов.")
        lines.append(f"До цели в {result.goal} ни разу не хватило — может, она "
                     "сейчас великовата. Поменять её можно в профиле.")

    if result.previous:
        lines.append(f"Неделей раньше было {result.previous}.")

    if result.team_name:
        place = (f", ты {result.team_place}-я из {result.team_people}"
                 if result.team_place else "")
        lines.append(f"Команда «{result.team_name}» — {result.team_total} шагов{place}.")

    if result.place and result.people > 1:
        lines.append(f"По всему приложению ты {result.place}-я из {result.people}.")

    lines += ["", "Новая неделя началась — счёт с нуля."]
    return "\n".join(lines)


async def for_user(session: AsyncSession, user: User, *,
                   timezone_name: str = DEFAULT_TIMEZONE,
                   today: date | None = None) -> Result:
    """Собрать итог прошлой недели для одного человека."""
    day = today or today_in(timezone_name)
    period = step_service.last_week_bounds(day)
    # Неделя перед прошлой: нужна, чтобы показать, с чем сравнивать.
    before = (period[0] - timedelta(days=step_service.WEEK_DAYS),
              period[0] - timedelta(days=1))

    rows = await step_service.global_top(session, limit=10 ** 6, me=user.id,
                                         timezone_name=timezone_name, period=period)
    mine = next((row for row in rows if row.user_id == user.id), None)
    previous = await step_service.week_rows(session, [user.id], period=before)

    team_name, team_total, team_place, team_people = "", 0, None, 0
    team = await teams.my_team(session, user.id)
    if team is not None:
        members = await teams.member_ids(session, team.id)
        team_rows = await step_service.week_rows(session, members, me=user.id,
                                                 period=period)
        team_name = team.name
        team_total = sum(row.steps for row in team_rows)
        team_place = step_service.place_of(team_rows, user.id)
        team_people = len(team_rows)

    return Result(
        user_id=user.id,
        steps=mine.steps if mine else 0,
        days_done=mine.days if mine else 0,
        goal=step_service.goal_for(user),
        previous=previous[0].steps if previous else 0,
        place=step_service.place_of(rows, user.id),
        people=len([row for row in rows if row.steps > 0]),
        team_name=team_name, team_total=team_total,
        team_place=team_place, team_people=team_people,
    )


async def due(session: AsyncSession, *, now_utc: datetime | None = None) -> list[Result]:
    """Кому сейчас (по их местному времени) пора отправить итог недели."""
    moment = now_utc or datetime.now(timezone.utc)

    zones = (await session.execute(
        select(User.timezone).where(
            User.onboarding_completed.is_(True), User.reminders_enabled.is_(True)
        ).distinct()
    )).scalars().all()
    ready = matching_zones(moment, SEND_AT, zones)
    if not ready:
        return []

    users = (await session.execute(
        select(User).where(
            User.onboarding_completed.is_(True), User.reminders_enabled.is_(True),
            User.timezone.in_(ready),
        )
    )).scalars().all()

    results: list[Result] = []
    for user in users:
        zone = user.timezone or DEFAULT_TIMEZONE
        day = today_in(zone, now=moment)
        if day.weekday() != SEND_WEEKDAY:
            continue

        result = await for_user(session, user, timezone_name=zone, today=day)
        # Неделя, в которой человек не сделал ни шага, — не повод писать ему,
        # что он последний.
        if result.walked:
            results.append(result)
    return results


__all__ = ["SEND_AT", "SEND_WEEKDAY", "Result", "due", "for_user", "render"]
