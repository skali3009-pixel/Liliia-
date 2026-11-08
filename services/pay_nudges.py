"""Дожим тех, кто прошёл анкету и не оплатил, — и тех, кто бросил оплату.

Зачем это нужно. С включённой оплатой бот молчал ровно там, где решается
главное: человек дошёл до конца анкеты, увидел свою норму и план на 30 дней,
не заплатил — и больше от бота не получал ничего. Все остальные письма
отбирают людей с доступом, а у неоплатившего его нет (`TRIAL_DAYS=0`: подписка
заводится сразу истёкшей). Письмо «анкета не закончена» по той же причине не
доходило вовсе.

Правила жёсткие, и они важнее текста.

- **Дожим об оплате — сервисное сообщение.** Он отправляется завершившим
  анкету независимо от согласия на новости и от общего выключателя
  `reminders_enabled`: напоминание относится к доступу, а не к рекламной
  рассылке. `/stop_ads` выключает только рекламные новости.
- **Брошенная оплата — исключение.** Человек сам открыл счёт; напомнить, что
  он остался, — не реклама. Одно сообщение на человека, без согласия.
- **Шесть писем за три дня.** Первое — через 12 часов после анкеты, дальше
  каждые 12 часов, у каждого письма свой текст. Окно — трое суток плюс два
  часа технического запаса, чтобы шестое успело уйти при задержках
  планировщика. Тихих часов нет: ровный интервал важнее.
- **Без выдуманной срочности.** Никаких таймеров, «последний день скидки» и
  «осталось мест». Скидка 290 ₽ — настоящая, только в промо-письме на первый
  месяц; таймера у неё нет.
- **Только новые.** Анкеты, закрытые до `START_DATE`, не получают ничего:
  старым пользователям никто не обещал рассылки продаж, и разослать её
  внезапно значит сделать то, о чём не договаривались.
- **Что отправлено — помнит база, а не память процесса.** Бот перезапускается
  каждые полчаса вместе с обновлением; память процесса письма не удержала бы.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import MarketingEvent, PlategaOrder, User
from services import analytics, platega
from services.age import adult_clause
from services.subscriptions import _aware, check_access
from utils.timeframe import DEFAULT_TIMEZONE, to_local, today_in

logger = logging.getLogger(__name__)

# Код события в журнале отправленного; подвид — какое именно письмо.
EVENT = "pay_nudge"

# Анкеты, закрытые раньше этого дня, дожима не получают.
START_DATE = date(2026, 10, 29)

# Что за письмо и через сколько дней после анкеты. Порядок важен.
PROMO = "promo"
PROMO_PRICE = 290
PROMO_MESSAGES = 6
PROMO_INTERVAL = timedelta(hours=12)
PROMO_WINDOW = timedelta(days=3, hours=2)
CART = "cart"

# Окно отправки брошенной оплаты по местному времени: днём, не ночью.
CART_FROM, CART_TO = time(9, 0), time(21, 0)
# Счёт «брошен», если с его создания прошло не меньше этого и не больше суток.
CART_AFTER = timedelta(minutes=30)
CART_UNTIL = timedelta(hours=24)

CB_STOP = "platega:nudge_stop"


@dataclass(frozen=True)
class Nudge:
    user_id: int
    kind: str             # promo1…promo6 / cart
    text: str
    order_id: str | None = None


def _first_name(user: User) -> str:
    name = (user.full_name or "").strip().split()
    return name[0][:30] if name else ""


def _greet(user: User) -> str:
    name = _first_name(user)
    return f"{name}, " if name else ""


def series_start(user: User) -> datetime | None:
    """Начало сетки промо-серии.

    Если первое письмо ушло с опозданием (например, старая версия писала
    через 16 часов вместо 12), сдвигаем сетку к фактической отправке: иначе
    задержка копится и последнее письмо не успевает в трёхдневное окно.
    """
    started = _aware(user.promo_started_at)
    last = _aware(user.promo_last_at)
    if not started or not last or user.promo_step < 1:
        return started
    expected = started + PROMO_INTERVAL * user.promo_step
    if last <= expected:
        return started
    return last - PROMO_INTERVAL * user.promo_step


def _norms(user: User) -> str:
    if user.daily_calories and user.daily_water_ml:
        return f"{user.daily_calories} ккал и {user.daily_water_ml} мл воды в день"
    return "суточная норма калорий и воды"


def render(kind: str, user: User) -> str:
    """Текст письма. Человек видит своё, а не общий призыв."""
    if kind.startswith(PROMO):
        step = int(kind[len(PROMO):] or 1)
        greet = _greet(user)
        if step == 1:
            return (
                f"🐆 {greet}анкета заполнена — норма и план готовы.\n\n"
                "Дальше начинается рутина, на которой обычно всё "
                "останавливается: считать калории, вспоминать, что уже "
                "съедено, искать тренировку, когда нет сил. AURA убирает "
                "именно эту рутину.\n\n"
                "Представь обычный день:\n"
                "📷 фото тарелки — и еда уже в дневнике, калории и БЖУ посчитаны;\n"
                "🍽 бот подсказывает блюдо под остаток нормы, а не запрещает есть;\n"
                "🏃 тренировка на 15 минут — и понятно, что именно делать;\n"
                "💧 вечером одна картина: еда, вода, шаги, вес и замеры.\n\n"
                "Это не про «начать с понедельника» и не про запреты. Это про "
                "ясность: видно, что происходит, и можно спокойно поправить, "
                "а не гадать.\n\n"
                "Скидка на первый месяц: 290 ₽ вместо 490 ₽."
            )
        if step == 2:
            return (
                f"🐆 {greet}ты уже знаешь свою норму — осталось сделать так, "
                "чтобы её было легко держать.\n\n"
                "Обычно срывается не сила воли, а мелочи: непонятно, сколько "
                "съел, что выбрать на ужин, где взять тренировку на 15 минут. "
                "AURA закрывает именно эти мелочи:\n\n"
                "📷 фото тарелки — запись уже готова;\n"
                "🍽 блюдо под остаток калорий и белка;\n"
                "🏃 короткая тренировка — и понятно, что делать;\n"
                "💧 вода и шаги — в один тап.\n\n"
                "Так проще не бросать: не нужно каждый день начинать заново.\n\n"
                "Скидка на первый месяц: 290 ₽ вместо 490 ₽."
            )
        if step == 3:
            return (
                f"🐆 {greet}за первый месяц ты увидишь не «идеальный результат», "
                "а понятную картину: что ешь, сколько двигаешься и что меняется.\n\n"
                "Что для этого есть:\n"
                "🍽 дневник еды по фото, голосу или тексту;\n"
                "🏃 17 программ и 103 упражнения с техникой;\n"
                "💧 вода, шаги, вес и замеры — на одном экране;\n"
                "📊 графики, по которым видно движение, даже когда весы стоят.\n\n"
                "Это не марафон «всё или ничего». Это спокойный способ каждый "
                "день видеть, что происходит, и возвращаться к своему плану.\n\n"
                "Скидка на первый месяц: 290 ₽ вместо 490 ₽."
            )
        if step == 4:
            return (
                f"🐆 {greet}первая неделя не требует героизма.\n\n"
                "Достаточно нескольких записей еды, пары коротких тренировок и "
                "воды — не идеально, а регулярно. Так появляется привычка, а не "
                "ещё один заброшенный «понедельник».\n\n"
                "AURA помогает не считать всё в голове:\n"
                "📷 фото или голос — и еда уже в дневнике;\n"
                "🍽 подбор блюд под остаток нормы;\n"
                "🏃 15 минут движения, когда нет сил;\n"
                "💧 вода и шаги — без отдельных таблиц.\n\n"
                "Скидка на первый месяц: 290 ₽ вместо 490 ₽."
            )
        if step == 5:
            return (
                f"🐆 {greet}если кажется, что «сейчас не время» — вот что "
                "на самом деле нужно:\n\n"
                "• не взвешивать каждую крошку — фото и быстрая правка порции;\n"
                "• не ходить в зал — короткая тренировка дома;\n"
                "• не менять всё сразу — один приём пищи и одна тренировка;\n"
                "• не держать всё в голове — дневник, вода и графики в одном месте.\n\n"
                "Начать можно с одного действия сегодня, а не с новой жизни с "
                "понедельника.\n\n"
                "Скидка на первый месяц: 290 ₽ вместо 490 ₽."
            )
        return (
            f"🐆 {greet}это последнее сообщение про скидку.\n\n"
            "Ты уже заполнил анкету и получил норму. Осталось открыть доступ "
            "и начать пользоваться:\n"
            "📷 еда по фото, голосу или тексту;\n"
            "🍽 подбор блюд под твою норму;\n"
            "🏃 короткие тренировки дома;\n"
            "💧 вода, шаги, вес, замеры и графики.\n\n"
            "Скидка действует три дня с момента анкеты. Если она ещё активна, "
            "самое время забрать первый месяц.\n\n"
            "Скидка на первый месяц: 290 ₽ вместо 490 ₽."
        )
    if kind == "d1":
        return (
            f"🐆 {_greet(user)}твой план на 30 дней готов и ждёт.\n\n"
            f"Я уже посчитала норму: {_norms(user)}. Остаётся открыть доступ — "
            "и первый приём пищи записывается за полминуты: фото, голос или "
            "пара слов.\n\n"
            "30 дней — 490 ₽, это около 16 ₽ в день. Автосписаний нет: "
            "продлеваешь, когда захочешь."
        )
    if kind == "d3":
        return (
            "Что откроется после оплаты:\n\n"
            "📷 запись еды по фото, голосу и тексту — калории и БЖУ за тебя;\n"
            "🍽 подбор блюд под то, что осталось до нормы;\n"
            "🏃 тренировки дома, каждое движение показано;\n"
            "💧 вода, шаги, вес и замеры — с графиком, чтобы видеть движение.\n\n"
            "30 дней — 490 ₽, без автосписаний. Если что-то смущает — напиши "
            "/problem, что именно: мне важно знать."
        )
    if kind == "d7":
        return (
            "Это моё последнее напоминание.\n\n"
            "Твой план и расчёты сохранены. Захочешь вернуться — открой "
            "/tariffs, и всё будет на месте. Больше писать про оплату я не буду."
        )
    if kind == CART:
        return (
            "Оплата AURA осталась незавершённой.\n\n"
            "Счёт сохранён — вернуться к нему можно кнопкой ниже. Платить "
            "дважды не придётся: когда платёж пройдёт, доступ откроется сам.\n"
            "Если что-то не получилось с картой или банком — напиши /problem."
        )
    raise ValueError(kind)


def keyboard(nudge: Nudge) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if nudge.kind == CART:
        builder.button(text="Вернуться к оплате", callback_data="platega:buy")
        if nudge.order_id:
            builder.button(text="Проверить оплату",
                           callback_data=f"platega:check:{nudge.order_id}")
    elif nudge.kind.startswith(PROMO):
        builder.button(text="Забрать первый месяц · 290 ₽",
                       callback_data="platega:promo290")
    elif nudge.kind == "d7":
        builder.button(text="Открыть тарифы", callback_data="platega:buy")
    else:
        builder.button(text="Открыть доступ · 490 ₽", callback_data="platega:buy")
    builder.adjust(1)
    return builder.as_markup()


def _in_window(moment: datetime, zone: str | None, start: time, end: time) -> bool:
    return start <= to_local(moment, zone).time() < end


async def due(session: AsyncSession, *, now_utc: datetime | None = None) -> list[Nudge]:
    """Кому из неоплативших сейчас пора написать. Ничего не отправляет и не пишет."""
    if not (config.PAYWALL and platega.enabled()):
        return []

    moment = now_utc or datetime.now(timezone.utc)
    start_at = datetime(START_DATE.year, START_DATE.month, START_DATE.day,
                        tzinfo=timezone.utc)
    admins = set(config.ADMIN_IDS)

    users = {u.id: u for u in (await session.execute(
        select(User).where(
            User.onboarding_completed.is_(True),
            User.legal_accepted_at.is_not(None),
            adult_clause(),
        )
    )).scalars().all() if u.id not in admins}
    if not users:
        return []

    sent: dict[int, set[str]] = {}
    for uid, kind, day in (await session.execute(
        select(MarketingEvent.user_id, MarketingEvent.kind, MarketingEvent.day).where(
            MarketingEvent.event == EVENT
        )
    )).all():
        sent.setdefault(uid, set()).add(kind)

    carts: dict[int, PlategaOrder] = {}
    for order in (await session.execute(
        select(PlategaOrder).where(
            PlategaOrder.status == "PENDING",
            PlategaOrder.url.is_not(None),
        ).order_by(PlategaOrder.created_at)
    )).scalars().all():
        created = _aware(order.created_at)
        if start_at <= created <= moment - CART_AFTER and moment - created <= CART_UNTIL:
            carts[order.user_id] = order

    result: list[Nudge] = []
    for uid, user in users.items():
        zone = user.timezone or DEFAULT_TIMEZONE
        done = sent.get(uid, set())

        order = carts.get(uid)
        if (order is not None and CART not in done
                and _in_window(moment, zone, CART_FROM, CART_TO)):
            if not (await check_access(session, uid)).allowed:
                result.append(Nudge(uid, CART, render(CART, user), order.id))
            continue

        started = series_start(user)
        if not started or user.promo_step >= PROMO_MESSAGES:
            continue
        if moment >= started + PROMO_WINDOW:
            continue
        if (await check_access(session, uid)).allowed:
            continue

        step = user.promo_step + 1
        next_at = started + PROMO_INTERVAL * step
        last = _aware(user.promo_last_at)
        if last and last + PROMO_INTERVAL > next_at:
            next_at = last + PROMO_INTERVAL
        if moment < next_at:
            continue
        result.append(Nudge(uid, f"{PROMO}{step}", render(f"{PROMO}{step}", user)))
    return result


async def mark(session: AsyncSession, nudge: Nudge, *, day: date | None = None,
               now_utc: datetime | None = None) -> None:
    """Записать, что письмо ушло. Коммит — на вызывающем."""
    session.add(MarketingEvent(
        user_id=nudge.user_id, event=EVENT, kind=nudge.kind,
        day=day or today_in(analytics.REPORT_TZ), count=1,
    ))
    if nudge.kind.startswith(PROMO):
        user = await session.get(User, nudge.user_id)
        if user is not None:
            try:
                step = int(nudge.kind[len(PROMO):])
            except ValueError:
                step = user.promo_step + 1
            user.promo_step = max(user.promo_step, step)
            user.promo_last_at = now_utc or datetime.now(timezone.utc)


async def report(session: AsyncSession) -> dict[str, object]:
    """Сколько людей вообще можно дожимать и что уже отправлено.

    Без этого блока «согласие на новости» остаётся неизвестным: письма
    уходят только согласившимся, и охват дожима нельзя отличить от нуля
    отправок.
    """
    finished = (await session.execute(
        select(MarketingEvent.user_id)
        .where(MarketingEvent.event == analytics.PROFILE_COMPLETED,
               MarketingEvent.day >= START_DATE)
        .distinct()
    )).scalars().all()

    consented = 0
    if finished:
        consented = int((await session.execute(
            select(func.count()).select_from(User)
            .where(User.id.in_(finished), User.marketing_consent.is_(True))
        )).scalar_one())

    sent = {f"{PROMO}{step}": 0 for step in range(1, PROMO_MESSAGES + 1)}
    sent["cart"] = 0
    rows = await session.execute(
        select(MarketingEvent.kind, func.sum(MarketingEvent.count))
        .where(MarketingEvent.event == EVENT, MarketingEvent.day >= START_DATE)
        .group_by(MarketingEvent.kind)
    )
    for kind, count in rows.all():
        if kind in sent:
            sent[kind] = int(count or 0)

    return {"finished": len(finished), "consented": consented, "sent": sent}


__all__ = ["CART", "CB_STOP", "EVENT", "Nudge", "PROMO",
           "PROMO_INTERVAL", "PROMO_MESSAGES", "PROMO_PRICE", "PROMO_WINDOW",
           "START_DATE", "due", "keyboard", "mark", "render", "report"]
