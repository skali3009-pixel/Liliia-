"""Дожим тех, кто прошёл анкету и не оплатил, — и тех, кто бросил оплату.

Зачем это нужно. С включённой оплатой бот молчал ровно там, где решается
главное: человек дошёл до конца анкеты, увидел свою норму и план на 30 дней,
не заплатил — и больше от бота не получал ничего. Все остальные письма
отбирают людей с доступом, а у неоплатившего его нет (`TRIAL_DAYS=0`: подписка
заводится сразу истёкшей). Письмо «анкета не закончена» по той же причине не
доходило вовсе.

Правила жёсткие, и они важнее текста.

- **Только тем, кто разрешил новости.** Звать оплатить — это реклама, а не
  служебное сообщение. Согласие `marketing_consent` спрашивают отдельным
  вопросом при знакомстве, и его отзывает `/stop_ads` и кнопка в самом письме.
- **Брошенная оплата — исключение.** Человек сам открыл счёт; напомнить, что
  он остался, — не реклама. Одно сообщение на человека, без согласия.
- **Не больше трёх писем и ни одного после недели.** На 1-й, 3-й и 7-й день
  после анкеты, в местный день, не чаще раза в сутки. Опоздавшее письмо
  отправляется не позже чем через день после срока, потом пропадает: поздний
  «вчерашний» дожим хуже тишины.
- **Без выдуманной срочности.** Никаких таймеров, «последний день скидки» и
  «осталось мест»: скидки нет. Только то, что человек получит, и цена.
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
from sqlalchemy import select
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
STEPS = (("d1", 1), ("d3", 3), ("d7", 7))
CART = "cart"

# Опоздавшее письмо уходит не позже чем через столько дней после срока.
LATE_DAYS = 1

# Окно отправки по местному времени: после полудня и до вечера.
SEND_FROM, SEND_TO = time(12, 0), time(20, 0)
# Для брошенной оплаты окно шире, но ночью тоже тихо.
CART_FROM, CART_TO = time(9, 0), time(21, 0)
# Счёт «брошен», если с его создания прошло не меньше этого и не больше суток.
CART_AFTER = timedelta(minutes=30)
CART_UNTIL = timedelta(hours=24)

CB_STOP = "platega:nudge_stop"


@dataclass(frozen=True)
class Nudge:
    user_id: int
    kind: str             # d1 / d3 / d7 / cart
    text: str
    order_id: str | None = None


def _first_name(user: User) -> str:
    name = (user.full_name or "").strip().split()
    return name[0][:30] if name else ""


def _greet(user: User) -> str:
    name = _first_name(user)
    return f"{name}, " if name else ""


def _norms(user: User) -> str:
    if user.daily_calories and user.daily_water_ml:
        return f"{user.daily_calories} ккал и {user.daily_water_ml} мл воды в день"
    return "суточная норма калорий и воды"


def render(kind: str, user: User) -> str:
    """Текст письма. Человек видит своё, а не общий призыв."""
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
    elif nudge.kind == "d7":
        builder.button(text="Открыть тарифы", callback_data="platega:buy")
        builder.button(text="Не напоминать", callback_data=CB_STOP)
    else:
        builder.button(text="Открыть доступ · 490 ₽", callback_data="platega:buy")
        builder.button(text="Не напоминать", callback_data=CB_STOP)
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
            User.reminders_enabled.is_(True),
            adult_clause(),
        )
    )).scalars().all() if u.id not in admins}
    if not users:
        return []

    finished = {uid: day for uid, day in (await session.execute(
        select(MarketingEvent.user_id, MarketingEvent.day).where(
            MarketingEvent.event == analytics.PROFILE_COMPLETED,
            MarketingEvent.day >= START_DATE,
        )
    )).all()}

    sent: dict[int, set[str]] = {}
    last_day: dict[int, date] = {}
    for uid, kind, day in (await session.execute(
        select(MarketingEvent.user_id, MarketingEvent.kind, MarketingEvent.day).where(
            MarketingEvent.event == EVENT
        )
    )).all():
        sent.setdefault(uid, set()).add(kind)
        last_day[uid] = max(day, last_day.get(uid, day))

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

    # Дни в журнале — московские, как во всём учёте; сравниваем с тем же поясом.
    today = today_in(analytics.REPORT_TZ, now=moment)

    result: list[Nudge] = []
    for uid, user in users.items():
        zone = user.timezone or DEFAULT_TIMEZONE
        done = sent.get(uid, set())
        # Не чаще раза в сутки, что бы это ни было.
        if last_day.get(uid) == today:
            continue

        order = carts.get(uid)
        wants_cart = (order is not None and CART not in done
                      and _in_window(moment, zone, CART_FROM, CART_TO))
        step = None
        if not wants_cart and user.marketing_consent and uid in finished \
                and _in_window(moment, zone, SEND_FROM, SEND_TO):
            age = (today - finished[uid]).days
            for kind, days in STEPS:
                if kind not in done and days <= age <= days + LATE_DAYS:
                    step = kind
                    break
        if not wants_cart and step is None:
            continue

        if (await check_access(session, uid)).allowed:
            continue

        if wants_cart:
            result.append(Nudge(uid, CART, render(CART, user), order.id))
        else:
            result.append(Nudge(uid, step, render(step, user)))
    return result


async def mark(session: AsyncSession, nudge: Nudge, *, day: date | None = None) -> None:
    """Записать, что письмо ушло. Коммит — на вызывающем."""
    session.add(MarketingEvent(
        user_id=nudge.user_id, event=EVENT, kind=nudge.kind,
        day=day or today_in(analytics.REPORT_TZ), count=1,
    ))


__all__ = ["CART", "CB_STOP", "EVENT", "LATE_DAYS", "Nudge", "START_DATE",
           "STEPS", "due", "keyboard", "mark", "render"]
