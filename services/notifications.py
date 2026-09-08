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

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (NotificationLog, NotificationPrefs, NotificationSnooze,
                    User)
from models.notification import (KIND_ACHIEVEMENT, KIND_EVENING, KIND_MEAL,
                                 KIND_MOVEMENT, KIND_TURN, KIND_WATER,
                                 KIND_WORLD, KINDS, PACE_ACTIVE,
                                 PACE_BALANCED, PACE_MINIMAL, PACES,
                                 RESULT_ACTED, RESULT_MUTED,
                                 RESULT_OPENED, RESULT_SNOOZED)
from services.context import Action
from utils.events import event_for
from utils.game import ACHIEVEMENT_BY_CODE
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
    # Последнее задание дня — это всё ещё «что сделать сейчас».
    "day": KIND_TURN,
    # А близкий уровень — про награду, и выключается вместе с достижениями.
    "level": KIND_ACHIEVEMENT,
    "evening": KIND_EVENING,
    "world": KIND_WORLD,
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
    KIND_WORLD: 72,
}

# Человек, который сам открыл приложение только что, всё уже видел своими
# глазами. Сообщение вдогонку — самый раздражающий вид напоминания.
RECENT_OPEN_MINUTES = 45

# «Позже» — не «никогда»: тема вернётся, но не сегодня же через час.
SNOOZE_HOURS = 3

# Усталость — не «да/нет», а величина. Растёт от молчания в ответ и от
# просьб отложить, падает от любого ответа и от времени: если бот давно
# ничего не писал, накопленное перестаёт иметь значение. Иначе один плохой
# день выключал бы уведомления навсегда.
FATIGUE_WINDOW = 5
IGNORE_WEIGHT = 0.25
SNOOZE_WEIGHT = 0.15
# За сколько часов тишины усталость уменьшается вдвое.
FATIGUE_HALF_LIFE = 48
# Выше этого — считаем, что человек устал: бюджет падает до одного.
TIRED_AT = 0.6

# Обучение на реакциях. Если человек месяцами не отвечает на воду, вода
# должна звучать реже — но не исчезнуть совсем: два неотвеченных сообщения
# не значат «никогда больше». Поэтому множитель ограничен снизу.
ADAPT_WINDOW_DAYS = 21
ADAPT_MIN_SAMPLE = 4
ADAPT_FLOOR = 0.65


# Утро. Первое за день сообщение в этих часах здоровается. Нижняя граница
# совпадает с EARLIEST_HOUR ниже: раньше бот всё равно не пишет, и окно с
# семи часов было бы обещанием, которого он не выполняет. — не отдельным
# сообщением «доброе утро, посмотри свой ход», а тем же самым, с которым
# бот и так пришёл. Отдельный утренний привет тратил бы сообщение из
# бюджета и не менял бы ничего: человеку всё равно пришлось бы открыть
# приложение, чтобы узнать, что ему предлагают.
MORNING_FROM, MORNING_TO = 9, 11

# Час, в который мир может показать событие. Один на весь день.
WORLD_HOUR = 10

# Раньше этого часа бот не пишет первым, даже если тихие часы уже кончились.
# Тихие часы — это «не буди», а здесь другое: в семь утра ещё ничего не
# успело случиться, и «воды сегодня не отмечено» — не наблюдение, а
# будильник по расписанию. Ровно то, от чего мы уходили. Замерено на двух
# месяцах: без этого предела сообщение уходило в 07:00 каждый день.
# На экране подсказка по-прежнему видна с самого утра — она там никого
# не будит.
EARLIEST_HOUR = 9

GREETING = (
    "Доброе утро.",
    "С добрым утром.",
    "Утро.",
    "Доброе утро!",
    "Утро доброе.",
)


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
    greeting: str = ""

    @property
    def message(self) -> str:
        """Текст сообщения целиком — тот, что уходит в чат.

        Собирается здесь, а не в планировщике: в планировщике его нельзя
        проверить тестом, а это единственное, что человек видит.
        """
        if self.kind == KIND_EVENING:
            # У итогов дня своя шапка: «твой ход» им не подходит, они не
            # про следующее действие, а про то, как сложился день.
            return self.text
        head = f"{self.greeting} " if self.greeting else ""
        return f"🐆 {head}Твой ход\n\n{self.text}"


# Награды приходят под своими кодами — их десятки, и перечислять каждую
# в списке категорий бессмысленно.
AWARD_CODES = frozenset(ACHIEVEMENT_BY_CODE)


def kind_of(code: str) -> str:
    if code in AWARD_CODES:
        return KIND_ACHIEVEMENT
    return KIND_OF.get(code, KIND_TURN)


def _world_action(user_id: int, day, game: dict, hour: int) -> Action | None:
    """Событие сегодняшнего дня — если оно есть и ещё не случилось.

    Соревноваться весом с обычными подсказками событие не может и не
    должно. Оно просит ровно того же — закрыть пару заданий, — но не
    полезнее, а приятнее. У человека с пустым днём всегда найдётся повод
    весомее («в дневнике пусто»), и событие проиграло бы каждый раз, то
    есть не пришло бы никогда. Поэтому у него свой момент: одно утро.
    Реже некуда — события бывают не каждый день, а остывание категории
    держит их на расстоянии в трое суток.

    Ничего не начисляет и не записывает: награду за событие выдаёт
    services/events.py, когда человек закроет задания. Здесь только чтение.
    """
    if hour != WORLD_HOUR:
        return None

    event = event_for(user_id, day.isoformat())
    if event is None:
        return None

    done = game.get("quests_done", 0)
    if done >= event.target:
        return None            # событие уже случилось, звать некуда

    left = event.target - done
    tail = ("" if done == 0 else
            f"\n\nОсталось закрыть {left} из {event.target}.")
    return Action("world", "Мир",
                  f"{event.icon} {event.title}\n\n{event.text}{tail}",
                  "Посмотреть мир", "world", score=1.25)


def fatigue(history: list[Sent], *, now: datetime | None = None) -> float:
    """Насколько человек устал от бота: от 0 до 1.

    Молчание в ответ добавляет, просьба отложить добавляет меньше, любой
    ответ вычитает. Потом накопленное гасится временем: бот, который давно
    молчит, не должен тащить за собой прошлую неделю.
    """
    recent = sorted(history, key=lambda row: row.sent_at, reverse=True)[:FATIGUE_WINDOW]
    if not recent:
        return 0.0

    score = 0.0
    for row in recent:
        if not row.result:
            score += IGNORE_WEIGHT
        elif row.result in {RESULT_SNOOZED, RESULT_MUTED}:
            score += SNOOZE_WEIGHT
        else:
            score -= IGNORE_WEIGHT
    score = max(0.0, min(1.0, score))

    if now is not None:
        quiet = (now - _aware(recent[0].sent_at)).total_seconds() / 3600
        score *= max(0.0, 1 - quiet / (2 * FATIGUE_HALF_LIFE))
    return round(score, 3)


def tired(history: list[Sent], *, now: datetime | None = None) -> bool:
    """Устал ли настолько, что пора резко убавить громкость."""
    return fatigue(history, now=now) >= TIRED_AT


def appetite(stats: dict, kind: str) -> float:
    """Множитель веса по прошлым реакциям на эту категорию.

    Меньше единицы — тема звучит реже. Ниже ADAPT_FLOOR не опускается
    никогда: человек, дважды не нажавший кнопку, не просил замолчать
    навсегда, а выключить категорию он может сам и явно.
    """
    sent, answered = stats.get(kind, (0, 0))
    if sent < ADAPT_MIN_SAMPLE:
        return 1.0                      # рано делать выводы
    rate = answered / sent
    if rate == 0:
        return ADAPT_FLOOR
    if rate < 0.25:
        return 0.85
    return 1.0


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
    day_seed: int = 0,
    appetite_for: float = 1.0,
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
    if prefs.quiet_at(local_hour) or local_hour < EARLIEST_HOUR:
        return None
    if kind in snoozed:
        return None

    if last_seen is not None:
        if now - _aware(last_seen) < timedelta(minutes=RECENT_OPEN_MINUTES):
            return None

    budget = prefs.budget
    floor = prefs.floor
    weariness = fatigue(history)
    if weariness:
        # Планка поднимается плавно, а не одной ступенькой: чем меньше
        # человек отвечает, тем весомее должен быть повод.
        floor += weariness * 0.5
    if weariness >= TIRED_AT:
        # Не замолкаем навсегда: одно действительно весомое сообщение в день
        # пройдёт. Ответит — счёт усталости пойдёт вниз сам.
        budget = min(budget, 1)

    if len(today) >= budget:
        return None

    if today:
        last = max(row.sent_at for row in today)
        if now - _aware(last) < prefs.gap:
            return None

    # Одна тема — одно сообщение в сутки. Без этого правила самая частая
    # тема съедает весь дневной бюджет: замеряно на двух месяцах —
    # старательный человек получал 2,8 сообщения в день, и почти все про
    # еду. Три раза за день сказать одно и то же — это не три напоминания,
    # это одно, повторённое трижды.
    if any(row.kind == kind for row in today):
        return None

    cooldown = timedelta(hours=COOLDOWN_HOURS.get(kind, 6))
    for row in history:
        if row.kind == kind and now - _aware(row.sent_at) < cooldown:
            return None

    # Прошлые реакции именно на эту тему. Не запрет, а громкость.
    if action.score * appetite_for < floor:
        return None

    morning = (MORNING_FROM <= local_hour < MORNING_TO and not today
               and kind != KIND_EVENING)
    return Push(user_id=user_id, kind=kind, code=action.code, text=action.text,
                cta=action.cta, target=action.target, amount=action.amount,
                greeting=GREETING[day_seed % len(GREETING)] if morning else "")


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


# Награда, полученная давнее этого срока, — уже не новость.
AWARD_FRESH_HOURS = 48


async def reactions(session: AsyncSession, user_id: int, *,
                    now_utc: datetime,
                    days: int = ADAPT_WINDOW_DAYS) -> dict[str, tuple[int, int]]:
    """Сколько по каждой теме отправлено и сколько из этого нашло отклик.

    Один сгруппированный запрос, а не строка на сообщение: считается это
    для каждого человека каждый час.
    """
    rows = (await session.execute(
        select(NotificationLog.kind, NotificationLog.result,
               func.count().label("n"))
        .where(NotificationLog.user_id == user_id,
               NotificationLog.sent_at >= now_utc - timedelta(days=days))
        .group_by(NotificationLog.kind, NotificationLog.result)
    )).all()

    stats: dict[str, list[int]] = {}
    for kind, result, count in rows:
        pair = stats.setdefault(kind, [0, 0])
        pair[0] += count
        # Откликом считаем действие и открытие приложения. «Позже» и
        # «сегодня не надо» — это ответ человека, но не тот, ради которого
        # стоило писать.
        if result in {RESULT_ACTED, RESULT_OPENED}:
            pair[1] += count
    return {kind: (sent, answered) for kind, (sent, answered) in stats.items()}


async def announced(session: AsyncSession, user_id: int, kind: str) -> set[str]:
    """Что по этой категории человеку уже говорили. Из истории, не из памяти."""
    rows = (await session.execute(
        select(NotificationLog.code)
        .where(NotificationLog.user_id == user_id, NotificationLog.kind == kind)
    )).scalars().all()
    return {code for code in rows if code}


async def fresh_award(session: AsyncSession, user_id: int, *,
                      now_utc: datetime) -> dict | None:
    """Новая награда, о которой ещё не говорили.

    Читаем таблицу наград, а не «свежие» из игрового пересчёта. Свежесть там
    живёт ровно один вызов: пересчёт помечает награду новой в тот раз, когда
    впервые её выдал. Движок уведомлений вызывает пересчёт каждый час — и,
    возьми он этот признак, съедал бы поздравление до того, как человек
    откроет приложение. На экране вспышки бы не было.
    """
    from models import Achievement

    said = await announced(session, user_id, KIND_ACHIEVEMENT)
    rows = (await session.execute(
        select(Achievement.code, Achievement.title)
        .where(Achievement.user_id == user_id,
               Achievement.earned_at >= now_utc - timedelta(hours=AWARD_FRESH_HOURS))
        .order_by(Achievement.earned_at.desc())
    )).all()

    for code, title in rows:
        if code in said:
            continue
        item = ACHIEVEMENT_BY_CODE.get(code)
        return {"code": code, "title": title,
                "icon": item.icon if item else "💎"}
    return None


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
    from services import evening
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
        if prefs.quiet_at(hour) or hour < EARLIEST_HOUR:
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

        # Все поводы сразу, а не по очереди с запасными вариантами.
        # Запасной вариант здесь не работал бы: подсказка «что сделать
        # сейчас» находится почти всегда, и событие мира, стоящее за ней,
        # не пришло бы никогда.
        options: list[Action] = []

        if hour == evening.EVENING_HOUR:
            summary = evening.render(parts["game"].get("quests") or [],
                                     seed=day.toordinal())
            if summary is not None:
                options.append(Action("evening", "Итоги дня", summary.text,
                                      "Посмотреть день", summary.target, score=1.1))

        # Награда — единственное сообщение, которое человек рад получить
        # просто так. Но и оно одно на награду: повторить поздравление
        # нельзя, поэтому сказанное записано в истории.
        award = await fresh_award(session, user.id, now_utc=moment)
        if award is not None:
            options.append(Action(award["code"], "Награда",
                                  f"{award['icon']} Новая награда: {award['title']}",
                                  "Посмотреть", "world", score=1.2))

        advice = await turn_service.peek_action(session, user, tz,
                                                now=moment, **parts)
        if advice is not None:
            options.append(advice)

        world = _world_action(user.id, day, parts["game"], hour)
        if world is not None:
            options.append(world)

        if not options:
            continue

        # Побеждает не тот, кто раньше в списке, а тот, чей повод весомее
        # именно для этого человека: темы, на которые он не отвечает,
        # звучат тише.
        stats = await reactions(session, user.id, now_utc=moment)
        action = max(options,
                     key=lambda item: item.score * appetite(stats, kind_of(item.code)))

        push = decide(action, user_id=user.id, prefs=prefs, local_hour=hour,
                      today=today, history=history, now=moment, snoozed=snoozed,
                      last_seen=seen, day_seed=day.toordinal(),
                      appetite_for=appetite(stats, kind_of(action.code)))
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
    "GREETING", "MIN_SCORE", "MORNING_FROM", "MORNING_TO",
    "RECENT_OPEN_MINUTES", "SNOOZE_HOURS",
    "Prefs", "Push", "Sent",
    "AWARD_FRESH_HOURS", "announced", "candidates", "decide", "due",
    "EARLIEST_HOUR", "WORLD_HOUR", "appetite", "fatigue", "fresh_award", "last_seen_of", "reactions", "history_for", "kind_of", "local_day_and_hour",
    "mark", "prefs_for", "remember", "save_prefs", "snooze", "snoozed_kinds",
    "sent_today", "tired",
]
