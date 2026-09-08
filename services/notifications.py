"""Кому, когда и что написать первым — и, чаще всего, не писать вовсе.

Главное правило: если сообщение не меняет следующее действие человека, его
не надо отправлять. Молчание здесь — не отказ работать, а решение.

Раньше бот писал по расписанию: вода в 16:00, дневник в 20:00, один и тот
же текст каждый день. Такое сообщение перестают читать примерно на третий
день, а вместе с ним перестают читать все остальные — включая то, ради
которого человек бота и держит.

Как устроено вместо этого. Раз в час по местному времени человека
собирается срез дня, и services/context.py называет одно самое уместное
действие — тот же код, который рисует «Твой ход» на экране. Дальше
начинается работа этого модуля: он смотрит, не спит ли человек, не просил
ли помолчать, не открыл ли приложение сам минуту назад, сколько сообщений
уже было сегодня, давно ли была эта же тема и реагирует ли он вообще. И
почти всегда решает промолчать.

Здесь только правила. Тексты — в services/context.py, отправка — в
scheduler.py, кнопки — в handlers/notifications.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (NotificationLog, NotificationPrefs, NotificationSnooze,
                    User)
from models.notification import (KIND_ACHIEVEMENT, KIND_EVENING, KIND_MEAL,
                                 KIND_MOVEMENT, KIND_TURN, KIND_WATER,
                                 KIND_WORLD, KINDS, PACE_ACTIVE,
                                 PACE_BALANCED, PACE_MINIMAL, PACES)
from services.context import Action
from utils.timeframe import DEFAULT_TIMEZONE, to_local, today_in

# Какому разделу настроек принадлежит совет. Человек выключает не «совет
# про клетчатку», а «еду» целиком — иначе настройки превращаются в анкету.
KIND_OF: dict[str, str] = {
    "water": KIND_WATER,
    "meal": KIND_MEAL,
    "protein": KIND_MEAL,
    "fiber": KIND_MEAL,
    "prep": KIND_MEAL,
    "steps": KIND_MOVEMENT,
    "movement": KIND_MOVEMENT,
    "rest": KIND_MOVEMENT,
    "checkin": KIND_TURN,
    "progress": KIND_TURN,
}

# Сколько сообщений в день допустимо. Не «сколько отправить» — сколько
# максимум, если для каждого нашёлся отдельный весомый повод.
BUDGET = {PACE_MINIMAL: 1, PACE_BALANCED: 3, PACE_ACTIVE: 4}

# Сколько часов между обычными сообщениями. Ответ на нажатие кнопки этим
# промежутком не ограничен: человек сам только что спросил.
GAP_HOURS = {PACE_MINIMAL: 8, PACE_BALANCED: 3, PACE_ACTIVE: 2}

# Ниже этого веса совет не стоит того, чтобы ради него звонить телефону.
# На экране такой совет по-прежнему показывается — там он никого не будит.
MIN_SCORE = {PACE_MINIMAL: 1.0, PACE_BALANCED: 0.6, PACE_ACTIVE: 0.45}

# Через сколько часов уместно вернуться к той же теме.
COOLDOWN_HOURS = {
    KIND_WATER: 5,
    KIND_MEAL: 5,
    KIND_MOVEMENT: 6,
    KIND_TURN: 4,
    KIND_EVENING: 20,
    KIND_ACHIEVEMENT: 12,
    KIND_WORLD: 48,
}

# Человек, который сам открыл приложение только что, всё уже видел своими
# глазами. Сообщение вдогонку — самый раздражающий вид напоминания.
RECENT_OPEN_MINUTES = 45

# «Позже» — не «никогда»: тема вернётся, но не сегодня же через час.
SNOOZE_HOURS = 3

# Усталость. Считаем самое простое, что честно: сколько последних сообщений
# подряд остались без единого ответа. Три подряд — человек не хочет
# разговаривать, и настаивать бесполезно.
FATIGUE_WINDOW = 5
FATIGUE_LIMIT = 3


@dataclass(frozen=True)
class Prefs:
    """Настройки человека. Строки в базе может не быть — тогда это значения
    по умолчанию, и они нигде не сохраняются, пока он ничего не менял."""

    turn: bool = True
    meal: bool = True
    water: bool = True
    movement: bool = True
    world: bool = True
    evening: bool = True
    achievement: bool = True
    quiet_from: int = 23
    quiet_to: int = 7
    pace: str = PACE_BALANCED

    def allows(self, kind: str) -> bool:
        return bool(getattr(self, kind, True))

    def quiet_at(self, hour: int) -> bool:
        """Тихие часы. Промежуток обычно переходит через полночь."""
        if self.quiet_from == self.quiet_to:
            return False
        if self.quiet_from < self.quiet_to:
            return self.quiet_from <= hour < self.quiet_to
        return hour >= self.quiet_from or hour < self.quiet_to

    @property
    def budget(self) -> int:
        return BUDGET.get(self.pace, BUDGET[PACE_BALANCED])

    @property
    def gap(self) -> timedelta:
        return timedelta(hours=GAP_HOURS.get(self.pace, GAP_HOURS[PACE_BALANCED]))

    @property
    def floor(self) -> float:
        return MIN_SCORE.get(self.pace, MIN_SCORE[PACE_BALANCED])


@dataclass(frozen=True)
class Sent:
    """Строка истории в том виде, в каком её читают правила."""

    kind: str
    code: str
    sent_at: datetime
    result: str = ""


@dataclass(frozen=True)
class Push:
    """Решение отправить. Ровно одно сообщение или ничего."""

    user_id: int
    kind: str
    code: str
    text: str
    cta: str
    target: str
    amount: int = 0


def kind_of(code: str) -> str:
    return KIND_OF.get(code, KIND_TURN)


def tired(history: list[Sent]) -> bool:
    """Устал ли человек от бота: подряд идущие сообщения без ответа."""
    ignored = 0
    for row in sorted(history, key=lambda s: s.sent_at, reverse=True)[:FATIGUE_WINDOW]:
        if row.result:
            break
        ignored += 1
    return ignored >= FATIGUE_LIMIT


def decide(  # noqa: PLR0911 — каждый выход это отдельная причина промолчать
    action: Action | None,
    *,
    user_id: int,
    prefs: Prefs,
    local_hour: int,
    today: list[Sent],
    history: list[Sent],
    now: datetime,
    snoozed: set[str],
    last_seen: datetime | None = None,
) -> Push | None:
    """Отправлять ли, и что именно. Ничего не читает и не пишет — только решает.

    Порядок проверок выбран по цене вопроса: сперва то, что человек сказал
    словами (выключил категорию, попросил тишины), потом то, что он показал
    поведением (сам зашёл, не отвечает), и только в конце — веса.
    """
    if action is None:
        return None

    kind = kind_of(action.code)
    if not prefs.allows(kind):
        return None
    if prefs.quiet_at(local_hour):
        return None
    if kind in snoozed:
        return None

    if last_seen is not None:
        if now - _aware(last_seen) < timedelta(minutes=RECENT_OPEN_MINUTES):
            return None

    budget = prefs.budget
    floor = prefs.floor
    if tired(history):
        # Не замолкаем навсегда: одно действительно весомое сообщение в день
        # пройдёт. Ответит — счёт молчания обнулится сам.
        budget = min(budget, 1)
        floor = max(floor, MIN_SCORE[PACE_MINIMAL])

    if len(today) >= budget:
        return None

    if today:
        last = max(row.sent_at for row in today)
        if now - _aware(last) < prefs.gap:
            return None

    cooldown = timedelta(hours=COOLDOWN_HOURS.get(kind, 6))
    for row in history:
        if row.kind == kind and now - _aware(row.sent_at) < cooldown:
            return None

    if action.score < floor:
        return None

    return Push(user_id=user_id, kind=kind, code=action.code, text=action.text,
                cta=action.cta, target=action.target, amount=action.amount)


def _aware(moment: datetime) -> datetime:
    """Момент из базы всегда в UTC, но часть драйверов отдаёт его без зоны."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --- работа с базой -------------------------------------------------------


async def prefs_for(session: AsyncSession, user_id: int) -> Prefs:
    row = await session.get(NotificationPrefs, user_id)
    if row is None:
        return Prefs()
    return Prefs(
        turn=row.turn, meal=row.meal, water=row.water, movement=row.movement,
        world=row.world, evening=row.evening, achievement=row.achievement,
        quiet_from=row.quiet_from, quiet_to=row.quiet_to, pace=row.pace,
    )


async def save_prefs(session: AsyncSession, user_id: int, **changes) -> Prefs:
    """Записать изменённые настройки. Незнакомые поля молча пропускаются."""
    row = await session.get(NotificationPrefs, user_id)
    if row is None:
        row = NotificationPrefs(user_id=user_id)
        session.add(row)

    for field in KINDS:
        if field in changes:
            setattr(row, field, bool(changes[field]))
    for field in ("quiet_from", "quiet_to"):
        if field in changes and changes[field] is not None:
            setattr(row, field, max(0, min(23, int(changes[field]))))
    if changes.get("pace") in PACES:
        row.pace = changes["pace"]

    await session.commit()
    return await prefs_for(session, user_id)


async def history_for(session: AsyncSession, user_id: int, *,
                      now_utc: datetime | None = None,
                      hours: int = 72) -> list[Sent]:
    """Последние сообщения человеку. Далеко в прошлое смотреть незачем:
    остывание считается часами, усталость — последними пятью."""
    moment = now_utc or datetime.now(timezone.utc)
    rows = (await session.execute(
        select(NotificationLog.kind, NotificationLog.code,
               NotificationLog.sent_at, NotificationLog.result)
        .where(NotificationLog.user_id == user_id,
               NotificationLog.sent_at >= moment - timedelta(hours=hours))
        .order_by(NotificationLog.sent_at.desc())
    )).all()
    return [Sent(kind=k, code=c, sent_at=_aware(s), result=r) for k, c, s, r in rows]


async def sent_today(session: AsyncSession, user_id: int, day) -> list[Sent]:
    rows = (await session.execute(
        select(NotificationLog.kind, NotificationLog.code,
               NotificationLog.sent_at, NotificationLog.result)
        .where(NotificationLog.user_id == user_id, NotificationLog.day == day)
    )).all()
    return [Sent(kind=k, code=c, sent_at=_aware(s), result=r) for k, c, s, r in rows]


async def snoozed_kinds(session: AsyncSession, user_id: int, *,
                        now_utc: datetime | None = None) -> set[str]:
    moment = now_utc or datetime.now(timezone.utc)
    rows = (await session.execute(
        select(NotificationSnooze.kind, NotificationSnooze.until)
        .where(NotificationSnooze.user_id == user_id)
    )).all()
    return {kind for kind, until in rows if _aware(until) > moment}


async def snooze(session: AsyncSession, user_id: int, kind: str, *,
                 until: datetime) -> None:
    """Отложить категорию. Повторная просьба заменяет предыдущую."""
    await session.execute(
        delete(NotificationSnooze).where(NotificationSnooze.user_id == user_id,
                                         NotificationSnooze.kind == kind)
    )
    session.add(NotificationSnooze(user_id=user_id, kind=kind, until=until))
    await session.commit()


async def remember(session: AsyncSession, push: Push, *, day,
                   now_utc: datetime | None = None) -> int:
    """Записать отправленное. Без этой записи не работает ничего: ни бюджет,
    ни остывание, ни усталость, ни ответ на вопрос, помогает ли это вообще."""
    row = NotificationLog(user_id=push.user_id, kind=push.kind, code=push.code,
                          day=day, sent_at=now_utc or datetime.now(timezone.utc))
    session.add(row)
    await session.commit()
    return row.id


async def mark(session: AsyncSession, user_id: int, kind: str, result: str, *,
               now_utc: datetime | None = None) -> None:
    """Отметить, чем закончилось последнее сообщение этой категории."""
    moment = now_utc or datetime.now(timezone.utc)
    row = (await session.execute(
        select(NotificationLog)
        .where(NotificationLog.user_id == user_id, NotificationLog.kind == kind,
               NotificationLog.result == "")
        .order_by(NotificationLog.sent_at.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        return
    row.result = result
    row.result_at = moment
    await session.commit()


async def candidates(session: AsyncSession, *,
                     now_utc: datetime | None = None) -> list[str]:
    """Часовые пояса, где сейчас начало часа — там и стоит думать."""
    from utils.timeframe import zones_at_minute

    moment = now_utc or datetime.now(timezone.utc)
    zones = (await session.execute(
        select(User.timezone).where(
            User.onboarding_completed.is_(True), User.reminders_enabled.is_(True)
        ).distinct()
    )).scalars().all()
    return zones_at_minute(moment, 0, zones)


async def due(session: AsyncSession, *,
              now_utc: datetime | None = None) -> list[tuple[User, Push, object]]:
    """Кому сейчас стоит написать. Возвращает человека, сообщение и его день.

    Порядок проверок здесь важнее их содержания. Полный срез дня — это
    полдюжины запросов на человека, и делать его каждый час для всех
    значило бы положить базу. Поэтому сначала идут отсечки, которые
    стоят один дешёвый запрос или вовсе ничего: тихие часы, исчерпанный
    бюджет, слишком свежее прошлое сообщение. Срез собирается только для
    тех, кому после всего этого действительно может уйти сообщение.
    """
    from services import turn as turn_service
    from services.comeback import gone_quiet

    moment = now_utc or datetime.now(timezone.utc)
    zones = await candidates(session, now_utc=moment)
    if not zones:
        return []

    users = (await session.execute(
        select(User).where(
            User.onboarding_completed.is_(True), User.reminders_enabled.is_(True),
            User.timezone.in_(zones),
        )
    )).scalars().all()
    if not users:
        return []

    # Кто пропал совсем — не наш случай: ему пишет services/comeback.py,
    # два раза и без единой цифры. Догонять его ещё и подсказками нельзя.
    quiet = await gone_quiet(session, users, now_utc=moment)

    out: list[tuple[User, Push, object]] = []
    for user in users:
        if user.id in quiet:
            continue

        tz = user.timezone or DEFAULT_TIMEZONE
        day, hour = local_day_and_hour(user, moment)

        prefs = await prefs_for(session, user.id)
        if prefs.quiet_at(hour):
            continue
        seen = last_seen_of(user)
        if seen is not None and moment - seen < timedelta(minutes=RECENT_OPEN_MINUTES):
            continue

        today = await sent_today(session, user.id, day)
        if len(today) >= prefs.budget:
            continue
        if today and moment - max(row.sent_at for row in today) < prefs.gap:
            continue

        history = await history_for(session, user.id, now_utc=moment)
        snoozed = await snoozed_kinds(session, user.id, now_utc=moment)

        # Дорогая часть — только для тех, кто дошёл сюда.
        parts = await turn_service.slice_for(session, user, tz)
        action = await turn_service.peek_action(session, user, tz, **parts)

        push = decide(action, user_id=user.id, prefs=prefs, local_hour=hour,
                      today=today, history=history, now=moment, snoozed=snoozed,
                      last_seen=seen)
        if push is not None:
            out.append((user, push, day))

    return out


def last_seen_of(user: User) -> datetime | None:
    """Когда человек последний раз был здесь — в приложении или в чате.

    Оба следа значат одно и то же: он сейчас занят ботом, и подсказывать
    ему нечего — он всё видит сам.
    """
    moments = [_aware(m) for m in (user.last_app_open, user.last_bot_action)
               if m is not None]
    return max(moments) if moments else None


def local_day_and_hour(user: User, moment: datetime) -> tuple:
    zone = user.timezone or DEFAULT_TIMEZONE
    local = to_local(moment, zone)
    return today_in(zone, now=moment), local.hour


__all__ = [
    "BUDGET", "COOLDOWN_HOURS", "FATIGUE_LIMIT", "GAP_HOURS", "KIND_OF",
    "MIN_SCORE", "RECENT_OPEN_MINUTES", "SNOOZE_HOURS",
    "Prefs", "Push", "Sent",
    "candidates", "decide", "due", "last_seen_of", "history_for", "kind_of", "local_day_and_hour",
    "mark", "prefs_for", "remember", "save_prefs", "snooze", "snoozed_kinds",
    "sent_today", "tired",
]
