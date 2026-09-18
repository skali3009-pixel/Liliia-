"""Цифры для владельца: люди, деньги и сходится ли одно с другим.

Три вопроса, на которые отчёт обязан отвечать без калькулятора:
сколько людей пришло и сколько из них реально пользуется ботом;
сколько денег он приносит и сколько съедает; сколько нужно платящих,
чтобы выйти в ноль.

Считаем осторожно: выручку — по тому, что реально доходит до владельца
(Telegram удерживает свою долю), расход — по всем запросам к модели, а
постоянные траты берём из настроек. Пока постоянные не заполнены, отчёт
не делает вид, что знает прибыль, — он говорит, чего не хватает.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import (
    ApiUsage,
    BodyMeasurement,
    Meal,
    Payment,
    User,
    WaterLog,
    WorkoutLog,
)
from utils.timeframe import DEFAULT_TIMEZONE, get_zone

# Таблицы, запись в которых означает «человек реально пользуется ботом».
# Открыть приложение и ничего не сделать — не пользование.
ACTIVITY = (
    (Meal.user_id, Meal.logged_at),
    (WaterLog.user_id, WaterLog.logged_at),
    (WorkoutLog.user_id, WorkoutLog.completed_at),
    (BodyMeasurement.user_id, BodyMeasurement.measured_at),
)


def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Audience:
    """Люди: сколько всего и сколько живых."""

    registered: int          # нажали /start
    onboarded: int           # дошли до конца анкеты
    joined: int              # пришли за период
    active: int              # что-то записали за период
    active_7d: int
    active_30d: int

    @property
    def stuck(self) -> int:
        """Начали анкету и не закончили — здесь теряются люди."""
        return max(self.registered - self.onboarded, 0)


@dataclass(frozen=True)
class Money:
    """Деньги за период, приведённые к тому, что реально доходит."""

    days: int
    stars: int
    revenue_usd: float       # выручка после доли Telegram
    tax_usd: float
    model_usd: float         # расход на распознавание и подбор
    fixed_usd: float         # сервер, бухгалтерия и прочее постоянное
    payers: int
    active: int

    @property
    def costs_usd(self) -> float:
        return round(self.model_usd + self.fixed_usd, 2)

    @property
    def profit_usd(self) -> float:
        return round(self.revenue_usd - self.tax_usd - self.costs_usd, 2)

    @property
    def per_active_usd(self) -> float:
        """Во сколько обходится один живой пользователь за период."""
        return round(self.model_usd / self.active, 3) if self.active else 0.0

    @property
    def per_payer_usd(self) -> float:
        """Сколько остаётся с одной подписки после доли Telegram и налога."""
        gross = config.SUB_PRICE_STARS * config.STAR_USD
        return round(gross * (1 - config.TAX_PERCENT / 100), 2)

    @property
    def breakeven_payers(self) -> int | None:
        """Сколько платящих нужно, чтобы расходы окупались.

        Главная цифра всего отчёта: она превращает «дорого или нет» в
        конкретное число людей.
        """
        income = self.per_payer_usd
        if income <= 0:
            return None
        return int(-(-self.costs_usd // income))     # округление вверх

    @property
    def known(self) -> bool:
        """Заполнены ли постоянные расходы — без них прибыль не посчитать."""
        return self.fixed_usd > 0


@dataclass(frozen=True)
class Activity:
    """Чем пользовались: по этим цифрам видно, что делать платным."""

    meals: int
    photos: int
    voices: int
    dishes: int
    workouts: int
    measurements: int


async def _count(session: AsyncSession, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    for condition in conditions:
        stmt = stmt.where(condition)
    return int((await session.execute(stmt)).scalar_one())


async def active_since(session: AsyncSession, since: datetime) -> int:
    """Сколько разных людей что-то записали с этого момента."""
    people: set[int] = set()
    for user_column, moment_column in ACTIVITY:
        rows = (await session.execute(
            select(user_column).where(moment_column >= since).distinct()
        )).scalars()
        people.update(int(row) for row in rows if row is not None)
    return len(people)


async def audience(session: AsyncSession, *, days: int = 1) -> Audience:
    """Люди за последние `days` суток плюс общие итоги."""
    since = now() - timedelta(days=days)
    return Audience(
        registered=await _count(session, User),
        onboarded=await _count(session, User, User.onboarding_completed.is_(True)),
        joined=await _count(session, User, User.created_at >= since),
        active=await active_since(session, since),
        active_7d=await active_since(session, now() - timedelta(days=7)),
        active_30d=await active_since(session, now() - timedelta(days=30)),
    )


async def activity(session: AsyncSession, *, days: int = 1) -> Activity:
    """Что люди делали за период."""
    since = now() - timedelta(days=days)

    async def api_calls(kind: str) -> int:
        # По времени запроса, а не по колонке «день»: сутки, отсчитанные
        # назад от сейчас, иначе прихватывают половину вчерашнего дня.
        return int((await session.execute(
            select(func.count(ApiUsage.id)).where(
                ApiUsage.kind == kind, ApiUsage.created_at >= since
            )
        )).scalar_one())

    return Activity(
        meals=await _count(session, Meal, Meal.logged_at >= since),
        photos=await api_calls("photo"),
        voices=await api_calls("voice"),
        dishes=await api_calls("build"),
        workouts=await _count(session, WorkoutLog, WorkoutLog.completed_at >= since),
        measurements=await _count(
            session, BodyMeasurement, BodyMeasurement.measured_at >= since
        ),
    )


async def money(session: AsyncSession, *, days: int = 30) -> Money:
    """Деньги за период. Расход берём по дню записи, выручку — по дате платежа."""
    since = now() - timedelta(days=days)
    day_from = since.date()

    stars = int((await session.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.paid_at >= since, Payment.refunded.is_(False)
        )
    )).scalar_one())
    payers = int((await session.execute(
        select(func.count(func.distinct(Payment.user_id))).where(
            Payment.paid_at >= since, Payment.refunded.is_(False)
        )
    )).scalar_one())
    model_usd = float((await session.execute(
        select(func.coalesce(func.sum(ApiUsage.cost_usd), 0.0)).where(ApiUsage.day >= day_from)
    )).scalar_one())

    revenue = stars * config.STAR_USD
    # Постоянные расходы заданы за месяц — переводим в длину периода.
    fixed = config.FIXED_COSTS_USD * days / 30

    return Money(
        days=days,
        stars=stars,
        revenue_usd=round(revenue, 2),
        tax_usd=round(revenue * config.TAX_PERCENT / 100, 2),
        model_usd=round(model_usd, 2),
        fixed_usd=round(fixed, 2),
        payers=payers,
        active=await active_since(session, since),
    )


async def owner_timezone(session: AsyncSession) -> str:
    """Часовой пояс владельца — по нему приходят отчёты."""
    if not config.ADMIN_IDS:
        return DEFAULT_TIMEZONE
    zone = (await session.execute(
        select(User.timezone).where(User.id.in_(config.ADMIN_IDS)).limit(1)
    )).scalar_one_or_none()
    return zone or DEFAULT_TIMEZONE


def owner_now(zone_name: str, *, moment: datetime | None = None) -> datetime:
    return (moment or now()).astimezone(get_zone(zone_name))


def is_time_for(zone_name: str, target: time, *, moment: datetime | None = None,
                weekday: int | None = None) -> bool:
    """Наступила ли у владельца та самая минута."""
    local = owner_now(zone_name, moment=moment)
    if (local.hour, local.minute) != (target.hour, target.minute):
        return False
    return weekday is None or local.weekday() == weekday


__all__ = ["ACTIVITY", "Activity", "Audience", "Money", "activity", "active_since",
           "audience", "is_time_for", "money", "now", "owner_now", "owner_timezone"]
