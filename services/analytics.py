"""Минимальный учёт: дошёл ли человек до пользы и откуда пришёл.

Что здесь считается и почему именно это.

- `bot_start` — запуск, который бот правда обработал. Уточнение отличает
  новый профиль от уже существовавшего: смешивать их нельзя, иначе «новые
  пользователи» в отчёте окажутся числом нажатий `/start`.
- `profile_completed` — анкета доведена до конца. Один раз за всё время:
  `onboarding_completed` поднимается однажды, и второго завершения у одного
  человека не бывает.
- `action_completed` — **завершённая** полезная операция, с видом. Не
  открытие экрана, не начало тренировки и не пустой ответ подбора.
- `first_action_completed` — первое наблюдаемое завершённое действие. Именно
  наблюдаемое: у людей, заведённых до этого учёта, первое в жизни действие
  случилось раньше, и выдавать сегодняшнее за первое — врать в воронке.
- `active_day` — день, в который человек сделал хоть что-то осмысленное.
  Ставится теми же обработчиками, что и полезное действие: фоновая проверка
  и доставленное уведомление активностью не считаются.

**Дедупликация.** Строка одна на (человек, событие, вид, день), и у неё есть
счётчик. Отсюда три разных правила, и каждое выбрано под своё событие:

- `once_ever` — событие бывает раз в жизни (`profile_completed`,
  `first_action_completed`). Повторная доставка не создаёт второй строки и
  не трогает счётчик.
- `once_a_day` — событие бывает раз в сутки (`bot_start`, `active_day`).
  Повторная доставка того же дня ничего не меняет.
- `count` — событие правда повторяется (`action_completed`). Здесь счётчик
  растёт, и это верно: второй записанный за день приём пищи — второе
  действие, а не дубль первого.

Про повторы у `action_completed` есть честное ограничение, и его надо знать:
оно ставится рядом с настоящей записью в базу (приём пищи, замер, тренировка).
Если один и тот же запрос придёт дважды, в базе появятся две записи — и учёт
их честно посчитает двумя. Это не потеря учёта, а свойство самих обработчиков,
и чинится оно там, а не здесь.

**Часовой пояс — московский, один на весь учёт.** Не местный у каждого: иначе
«активные за день» складывались бы из суток, которые начались в разное время,
и сумма по дням не сошлась бы ни с чем.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import MarketingEvent, User
from utils.timeframe import today_in

logger = logging.getLogger(__name__)

# Пояс отчёта. Тот же, что принят в проекте по умолчанию.
REPORT_TZ = "Europe/Moscow"

# Коды событий.
BOT_START = "bot_start"
PROFILE_COMPLETED = "profile_completed"
ACTION_COMPLETED = "action_completed"
FIRST_ACTION = "first_action_completed"
ACTIVE_DAY = "active_day"

# Уточнения к запуску.
NEW_PROFILE = "new"
EXISTING_PROFILE = "existing"

# Виды полезных действий. Список закрытый: свободная строка здесь означала бы,
# что в отчёте однажды появится вид, которого никто не заводил.
ACTIONS = ("meal", "cube", "measure", "workout")

# Как вид действия называется в отчёте человеку.
ACTION_NAMES = {
    "meal": "Записана еда",
    "cube": "Подобран вариант еды",
    "measure": "Записан вес или замер",
    "workout": "Завершена тренировка",
}

# День, с которого учёт вообще существует. Всё, что было раньше, здесь не
# лежит, и восстанавливать это догадками нельзя: отчёт, в котором часть
# чисел настоящая, а часть придумана, хуже отсутствующего.
STARTED_ON = date(2026, 9, 20)


def _today() -> date:
    return today_in(REPORT_TZ)


async def _row(session: AsyncSession, user_id: int, event: str, kind: str,
               day: date) -> MarketingEvent | None:
    return (await session.execute(
        select(MarketingEvent).where(
            MarketingEvent.user_id == user_id, MarketingEvent.event == event,
            MarketingEvent.kind == kind, MarketingEvent.day == day,
        )
    )).scalar_one_or_none()


async def _seen_ever(session: AsyncSession, user_id: int, event: str) -> bool:
    return (await session.execute(
        select(MarketingEvent.id).where(
            MarketingEvent.user_id == user_id, MarketingEvent.event == event
        ).limit(1)
    )).first() is not None


async def note(session: AsyncSession, user_id: int, event: str, *,
               kind: str = "", once: str = "count") -> bool:
    """Отметить событие. True — если запись правда изменилась.

    Ничего не коммитит: вызывается рядом с настоящей записью в базу и уезжает
    вместе с ней. Учёт, который сохранился, а действие — нет, хуже пустого
    учёта: цифра есть, а за ней ничего.
    """
    if once == "once_ever" and await _seen_ever(session, user_id, event):
        return False

    today = _today()
    row = await _row(session, user_id, event, kind, today)

    if row is None:
        session.add(MarketingEvent(user_id=user_id, event=event, kind=kind,
                                   day=today, count=1))
        return True

    if once in {"once_ever", "once_a_day"}:
        return False

    row.count += 1
    return True


async def useful_action(session: AsyncSession, user_id: int, kind: str) -> None:
    """Полезное действие завершено: отметить его, первый раз и активный день.

    Три отметки идут вместе нарочно — они об одном и том же событии, и
    поставить их порознь значит однажды получить «активных больше, чем
    сделавших хоть что-то».
    """
    if kind not in ACTIONS:
        logger.warning("Неизвестный вид полезного действия: %s", kind)
        return

    await note(session, user_id, ACTION_COMPLETED, kind=kind)
    await note(session, user_id, FIRST_ACTION, once="once_ever")
    await note(session, user_id, ACTIVE_DAY, once="once_a_day")


@dataclass(frozen=True)
class Report:
    """Воронка за период. Всё — числа людей, кроме явно названного."""

    since: date
    until: date
    starts_new: int          # людей, у кого в периоде завёлся профиль
    starts_existing: int     # людей, уже существовавших, кто запускал бота
    profiles: int            # людей, завершивших анкету
    first_actions: int       # людей, у кого первое полезное действие
    active_people: int       # людей, у кого был хоть один активный день
    active_days: int         # активных дней всего (людей × дни)
    actions: dict[str, int]  # вид действия → сколько раз (это события, не люди)
    sources: dict[str, int]  # первый источник → сколько новых людей


async def report(session: AsyncSession, *, days: int = 30,
                 exclude: set[int] | None = None) -> Report:
    """Собрать воронку за последние `days` дней.

    `exclude` — номера, которых в рабочих показателях быть не должно: свои и
    тестовые. Без этого первые же цифры оказываются про владельца.
    """
    until = _today()
    since = until - timedelta(days=days - 1)
    лишние = exclude or set()

    async def людей(event: str, kind: str | None = None) -> int:
        stmt = select(func.count(func.distinct(MarketingEvent.user_id))).where(
            MarketingEvent.event == event,
            MarketingEvent.day >= since, MarketingEvent.day <= until,
        )
        if kind is not None:
            stmt = stmt.where(MarketingEvent.kind == kind)
        if лишние:
            stmt = stmt.where(MarketingEvent.user_id.not_in(лишние))
        return int((await session.execute(stmt)).scalar_one())

    # Активных дней — это строки, а не люди: одна строка и есть один день.
    дней_стмт = select(func.count()).select_from(MarketingEvent).where(
        MarketingEvent.event == ACTIVE_DAY,
        MarketingEvent.day >= since, MarketingEvent.day <= until,
    )
    if лишние:
        дней_стмт = дней_стмт.where(MarketingEvent.user_id.not_in(лишние))

    действия_стмт = select(MarketingEvent.kind, func.sum(MarketingEvent.count)).where(
        MarketingEvent.event == ACTION_COMPLETED,
        MarketingEvent.day >= since, MarketingEvent.day <= until,
    )
    if лишние:
        действия_стмт = действия_стмт.where(MarketingEvent.user_id.not_in(лишние))
    действия_стмт = действия_стмт.group_by(MarketingEvent.kind)

    источники_стмт = select(User.first_source, func.count()).where(
        User.first_source.is_not(None)
    )
    if лишние:
        источники_стмт = источники_стмт.where(User.id.not_in(лишние))
    источники_стмт = источники_стмт.group_by(User.first_source)

    return Report(
        since=since,
        until=until,
        starts_new=await людей(BOT_START, NEW_PROFILE),
        starts_existing=await людей(BOT_START, EXISTING_PROFILE),
        profiles=await людей(PROFILE_COMPLETED),
        first_actions=await людей(FIRST_ACTION),
        active_people=await людей(ACTIVE_DAY),
        active_days=int((await session.execute(дней_стмт)).scalar_one()),
        actions={вид: int(сколько) for вид, сколько in
                 (await session.execute(действия_стмт)).all()},
        sources={метка: int(сколько) for метка, сколько in
                 (await session.execute(источники_стмт)).all()},
    )


__all__ = ["ACTIONS", "ACTION_COMPLETED", "ACTIVE_DAY", "BOT_START",
           "EXISTING_PROFILE", "FIRST_ACTION", "NEW_PROFILE",
           "PROFILE_COMPLETED", "REPORT_TZ", "Report", "note", "report",
           "useful_action"]
