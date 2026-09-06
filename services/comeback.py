"""Возвращение: письмо тому, кто перестал заходить.

Самая частая смерть такого приложения — тихая. Человек пропускает день,
потом неделю, и больше не открывает: не потому, что передумал, а потому,
что стало неловко возвращаться. Бот при этом молчит, а владелец видит
только медленно падающую цифру «активных» в недельном отчёте.

Поэтому здесь письмо, а не напоминание. Правила у него жёсткие, и они
важнее самого текста:

- Ни слова упрёка и ни одной цифры про тело: ни веса, ни калорий, ни
  «ты пропустила шесть дней». Человек и так знает, что не заходил.
- Максимум два письма за одно отсутствие: на третий день и на десятый.
  Дальше тишина — навсегда, пока человек сам не вернётся. Никаких
  «мы скучаем» каждую неделю.
- Считаем не по дневнику игры, а по любому следу: еда, вода, тренировка,
  замер. Написать «тебя не было» тому, кто вчера отмечал воду, — верный
  способ, чтобы бота выключили.
- Кто выключил напоминания, не получает ничего.

Состояние нигде не хранится: письмо уходит ровно на третий и на десятый
день тишины. Вернулся — счёт начинается заново сам собой.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from services.metrics import ACTIVITY
from utils.timeframe import DEFAULT_TIMEZONE, matching_zones, to_local, today_in

logger = logging.getLogger(__name__)

# На третий день тишины и на десятый. Между ними — ничего.
AWAY_FIRST = 3
AWAY_SECOND = 10
STAGES = (AWAY_FIRST, AWAY_SECOND)

# Полдень: утро занято сборами, вечер — усталостью, а днём письмо просто
# лежит в чате и ждёт.
SEND_AT = time(12, 0)

# Через сколько дней тишины замолкают ежедневные напоминания. Человеку,
# который бросил бота полгода назад, «сегодня ещё нет ни одной записи о еде»
# приходило каждый вечер — это не напоминание, это преследование. Пропал —
# ежедневное молчит, работают только два письма отсюда.
QUIET_AFTER = 2


@dataclass(frozen=True)
class Comeback:
    """Кому пишем и что."""

    user_id: int
    days: int
    started: bool      # успел хоть что-то записать до того, как пропал
    zones_open: int    # сколько мест в его мире уже открыто
    text: str


async def last_trace(session: AsyncSession, user_ids: list[int]) -> dict[int, datetime]:
    """Последний след человека: еда, вода, тренировка или замер.

    Именно любой след, а не только запись еды: человек мог всю неделю
    отмечать воду, и «тебя не было» в ответ на это — обидная неправда.
    """
    seen: dict[int, datetime] = {}
    if not user_ids:
        return seen

    for user_column, moment_column in ACTIVITY:
        rows = (await session.execute(
            select(user_column, func.max(moment_column))
            .where(user_column.in_(user_ids)).group_by(user_column)
        )).all()
        for raw_id, moment in rows:
            if raw_id is None or moment is None:
                continue
            user_id = int(raw_id)
            if user_id not in seen or moment > seen[user_id]:
                seen[user_id] = moment
    return seen


def _utc(moment: datetime) -> datetime:
    """Момент из базы всегда в UTC, но часть драйверов отдаёт его без зоны."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def gone_quiet(session: AsyncSession, users, *,
                     now_utc: datetime | None = None) -> set[int]:
    """Кто пропал настолько, что ежедневные напоминания ему уже не помогают.

    Считается по любому следу — еде, воде, тренировке, замеру, — поэтому
    человек, который вчера отметил хотя бы стакан воды, остаётся своим.
    """
    moment = now_utc or datetime.now(timezone.utc)
    edge = moment - timedelta(days=QUIET_AFTER)
    seen = await last_trace(session, [user.id for user in users])

    quiet: set[int] = set()
    for user in users:
        last = seen.get(user.id) or user.created_at
        if _utc(last) < edge:
            quiet.add(user.id)
    return quiet


def _days_away(last: datetime | None, created: datetime, zone: str | None,
               today: date) -> int:
    """Сколько дней тишины. Ноль — был сегодня или вчера."""
    moment = last or created
    return max((today - to_local(moment, zone).date()).days, 0)


def render(days: int, *, started: bool, zones_open: int) -> str:
    """Текст письма. Без упрёков, без цифр про тело, без «мы скучаем»."""
    if not started:
        # Человек завёл дневник и ни разу в него не заглянул. Ему нужен не
        # возврат, а первый шаг — и шаг должен быть очень маленьким.
        if days >= AWAY_SECOND:
            return (
                "🐆 Больше не напомню — дальше только по твоему желанию.\n\n"
                "Дневник останется на месте: анкета заполнена, норма посчитана. "
                "Захочешь начать — просто пришли фото любой еды.\n\n"
                "Выключить такие сообщения совсем: «⚙️ Профиль» → напоминания."
            )
        return (
            "🐆 Дневник готов, а первой записи так и нет.\n\n"
            "Первый шаг маленький: сфотографируй то, что ешь прямо сейчас — "
            "хоть кофе, хоть печенье. Считать и взвешивать ничего не надо, "
            "это моя работа.\n\n"
            "Можно и словами: «два бутерброда с сыром»."
        )

    if days >= AWAY_SECOND:
        return (
            "🐆 Это последнее напоминание — больше писать не буду.\n\n"
            "Всё твоё на месте и никуда не денется. Захочешь вернуться — "
            "просто запиши что-нибудь, я подхвачу с того места, где мы "
            "остановились.\n\n"
            "Выключить такие сообщения совсем: «⚙️ Профиль» → напоминания."
        )

    kept = ""
    if zones_open:
        kept = (f"\n\nВ твоём мире открыто мест: {zones_open}. "
                "Открытое остаётся открытым — оно не закрывается от перерыва.")

    return (
        "🐆 Я тут.\n\n"
        "Перерыв — это просто перерыв, а не начало сначала." + kept + "\n\n"
        "Если захочешь вернуться, начни с самого мелкого: стакан воды или "
        "одна запись о еде. Этого достаточно."
    )


async def due(session: AsyncSession, *, now_utc: datetime | None = None) -> list[Comeback]:
    """Кому сейчас (по их местному времени) пора написать.

    Как и остальные напоминания, проверяется раз в минуту: сначала ищем
    часовые пояса, где сейчас полдень, и только потом читаем людей.
    """
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
    if not users:
        return []

    seen = await last_trace(session, [user.id for user in users])

    letters: list[Comeback] = []
    for user in users:
        zone = user.timezone or DEFAULT_TIMEZONE
        today = today_in(zone, now=moment)
        last = seen.get(user.id)
        days = _days_away(last, user.created_at, zone, today)
        if days not in STAGES:
            continue

        zones_open = await _zones_open(session, user, zone) if last else 0
        letters.append(Comeback(
            user_id=user.id, days=days, started=last is not None,
            zones_open=zones_open,
            text=render(days, started=last is not None, zones_open=zones_open),
        ))

    return letters


async def _zones_open(session: AsyncSession, user: User, zone: str) -> int:
    """Сколько мест в мире человека уже открыто — и видел ли он их вообще.

    Мир живёт в приложении. Тому, кто вёл дневник только перепиской в чате,
    строка «в твоём мире открыто три места» ничего не говорит, поэтому
    сначала проверяем, открывал ли он этот экран хоть раз.

    Читаем состояние сами, а не через `world.state`: та заодно отмечает в
    базе показанные открытия, а фоновая рассылка ничего отмечать не должна.
    """
    try:
        from models import DayStat
        from services.world import facts
        from utils.world import build

        seen = (await session.execute(
            select(func.max(DayStat.world_open)).where(DayStat.user_id == user.id)
        )).scalar_one_or_none()
        if not seen:
            return 0

        return sum(1 for state in build(await facts(session, user, timezone_name=zone))
                   if state.open)
    except Exception:  # noqa: BLE001 — без мира письмо просто короче
        logger.warning("Не удалось прочитать мир для %s", user.id, exc_info=True)
        return 0


__all__ = ["AWAY_FIRST", "AWAY_SECOND", "QUIET_AFTER", "SEND_AT", "STAGES",
           "Comeback", "due", "gone_quiet", "last_trace", "render"]
