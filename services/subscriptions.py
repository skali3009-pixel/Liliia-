"""Доступ к приложению: пробный период, подписка, продление и окончание.

Правила простые:
- новый человек получает пробный период один раз;
- оплата продлевает доступ от текущей даты окончания, а не «сначала»,
  чтобы оплаченные дни не сгорали;
- когда срок вышел, доступ закрывается, но данные остаются на месте —
  оплатил снова и продолжил с того же места.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import (
    AppState,
    Payment,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
    User,
)

logger = logging.getLogger(__name__)

# Дата «никогда не кончится». Обычному сроку нужна конкретная дата — колонка
# не пустая, — а вечному доступу дата не нужна вовсе. Ставим заведомо далёкую
# и одну и ту же: в выгрузке базы сразу видно, что это не настоящий срок.
FOREVER = datetime(2099, 1, 1, tzinfo=timezone.utc)

# Отметка в app_state: в какой момент доступ стал платным. Ставится один раз,
# и по ней видно, кому бот достался бесплатно навсегда.
PAYWALL_STARTED = "paywall_started_at"


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime | None) -> datetime | None:
    """Время из базы бывает без зоны (SQLite) — считаем такое временем UTC."""
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Access:
    """Есть ли доступ и что показать человеку."""

    allowed: bool
    status: SubscriptionStatus
    expires_at: datetime | None
    days_left: int
    is_admin: bool = False
    is_recurring: bool = False
    is_lifetime: bool = False

    @property
    def is_trial(self) -> bool:
        return self.status == SubscriptionStatus.TRIAL

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "status": self.status.value,
            "days_left": self.days_left,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_trial": self.is_trial,
            "is_recurring": self.is_recurring,
            "is_lifetime": self.is_lifetime,
        }


def _days_left(expires_at: datetime | None) -> int:
    """Сколько полных дней осталось; 0 — если срок уже вышел."""
    expires = _aware(expires_at)
    if expires is None:
        return 0
    left = expires - now()
    return max(int(left.total_seconds() // 86400) + (1 if left.total_seconds() % 86400 else 0), 0)


def is_admin(user_id: int) -> bool:
    """У владельца доступ всегда: иначе он не сможет починить собственный бот."""
    return user_id in config.ADMIN_IDS


async def get_subscription(session: AsyncSession, user_id: int) -> Subscription | None:
    stmt = select(Subscription).where(Subscription.user_id == user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def ensure_trial(session: AsyncSession, user_id: int) -> Subscription:
    """Выдать пробный период, если этот человек его ещё не получал."""
    subscription = await get_subscription(session, user_id)
    if subscription is not None:
        return subscription

    subscription = Subscription(
        user_id=user_id,
        status=SubscriptionStatus.TRIAL,
        source=SubscriptionSource.TRIAL,
        expires_at=now() + timedelta(days=config.TRIAL_DAYS),
        trial_used=True,
    )
    session.add(subscription)
    await session.commit()
    logger.info("Пробный период выдан пользователю %s на %d дней", user_id, config.TRIAL_DAYS)
    return subscription


async def check_access(session: AsyncSession, user_id: int) -> Access:
    """Текущее состояние доступа. Ничего не создаёт и не меняет."""
    if is_admin(user_id):
        return Access(
            allowed=True,
            status=SubscriptionStatus.ACTIVE,
            expires_at=None,
            days_left=9999,
            is_admin=True,
        )

    subscription = await get_subscription(session, user_id)
    if subscription is None:
        return Access(False, SubscriptionStatus.EXPIRED, None, 0)

    # Бесплатно навсегда — считать нечего: срок не идёт, платить не нужно.
    if subscription.lifetime:
        return Access(
            allowed=True,
            status=SubscriptionStatus.ACTIVE,
            expires_at=None,
            days_left=0,
            is_lifetime=True,
        )

    expires = _aware(subscription.expires_at)
    alive = expires is not None and expires > now()
    status = subscription.status if alive else SubscriptionStatus.EXPIRED

    return Access(
        allowed=alive,
        status=status,
        expires_at=expires,
        days_left=_days_left(subscription.expires_at),
        is_recurring=subscription.is_recurring,
    )


async def activate(
    session: AsyncSession,
    user_id: int,
    *,
    days: int,
    source: SubscriptionSource,
    amount: int = 0,
    charge_id: str = "",
    is_recurring: bool = False,
) -> Subscription:
    """Продлить доступ. Оплаченные дни прибавляются к уже оставшимся."""
    subscription = await get_subscription(session, user_id)
    start = now()

    if subscription is None:
        subscription = Subscription(user_id=user_id, expires_at=start, trial_used=True)
        session.add(subscription)
    else:
        current = _aware(subscription.expires_at)
        # Заплатил раньше, чем кончилось, — остаток не сгорает.
        if current and current > start:
            start = current

    subscription.status = SubscriptionStatus.ACTIVE
    subscription.source = source
    subscription.expires_at = start + timedelta(days=days)
    subscription.is_recurring = is_recurring
    subscription.warned_at = None

    if amount or charge_id:
        session.add(
            Payment(
                user_id=user_id,
                amount=amount,
                days=days,
                charge_id=charge_id,
                is_recurring=is_recurring,
            )
        )

    await session.commit()
    logger.info(
        "Доступ продлён: пользователь %s, +%d дней, до %s, источник %s",
        user_id, days, subscription.expires_at, source.value,
    )
    return subscription


async def expire_overdue(session: AsyncSession) -> list[int]:
    """Пометить истёкшие подписки. Возвращает тех, у кого доступ только что кончился."""
    stmt = select(Subscription).where(
        Subscription.expires_at <= now(),
        Subscription.status != SubscriptionStatus.EXPIRED,
        Subscription.lifetime.is_(False),
    )
    rows = list((await session.execute(stmt)).scalars())
    for subscription in rows:
        subscription.status = SubscriptionStatus.EXPIRED

    if rows:
        await session.commit()
    return [row.user_id for row in rows]


async def expiring_soon(session: AsyncSession, *, days: int = 3) -> list[Subscription]:
    """Кому пора напомнить об окончании — по одному разу на срок."""
    edge = now() + timedelta(days=days)
    stmt = select(Subscription).where(
        Subscription.status != SubscriptionStatus.EXPIRED,
        Subscription.expires_at > now(),
        Subscription.expires_at <= edge,
        Subscription.warned_at.is_(None),
        # У кого списание автоматическое, напоминать не о чем.
        Subscription.is_recurring.is_(False),
        Subscription.lifetime.is_(False),
    )
    return list((await session.execute(stmt)).scalars())


async def mark_warned(session: AsyncSession, subscription: Subscription) -> None:
    subscription.warned_at = now()
    await session.commit()


async def grant_lifetime(session: AsyncSession, user_ids: list[int]) -> int:
    """Открыть перечисленным людям доступ навсегда."""
    if not user_ids:
        return 0

    existing = {
        row.user_id: row
        for row in (await session.execute(
            select(Subscription).where(Subscription.user_id.in_(user_ids))
        )).scalars()
    }

    changed = 0
    for user_id in user_ids:
        subscription = existing.get(user_id)
        if subscription is None:
            subscription = Subscription(user_id=user_id, trial_used=True)
            session.add(subscription)
        elif subscription.lifetime:
            continue          # уже навсегда — второй раз не нужно

        subscription.lifetime = True
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.source = SubscriptionSource.MANUAL
        subscription.expires_at = FOREVER
        subscription.warned_at = None
        changed += 1

    await session.commit()
    return changed


async def grandfather_existing(session: AsyncSession) -> int:
    """В момент включения платного доступа оставить бота бесплатным тем,
    кто уже им пользовался.

    Человек пришёл, когда бот был бесплатным, и завёл здесь свой дневник.
    Закрыть ему доступ одним обновлением — обмануть его задним числом.
    Поэтому все, кто был в боте на момент включения оплаты, остаются с ним
    навсегда; платит только тот, кто придёт после.

    Срабатывает ровно один раз за всю жизнь бота: отметка о моменте
    включения хранится в базе, а не в файле, и переживает переустановку
    сервера вместе с резервной копией.
    """
    if not config.PAYWALL:
        # Пока бот бесплатен для всех, делить людей не на что и границу
        # проводить рано.
        return 0

    marker = await session.get(AppState, PAYWALL_STARTED)
    if marker is not None:
        return 0

    user_ids = list((await session.execute(select(User.id))).scalars())
    session.add(AppState(key=PAYWALL_STARTED, value=now().isoformat(timespec="seconds")))
    granted = await grant_lifetime(session, user_ids)
    await session.commit()

    logger.info(
        "Платный доступ включён. Бесплатно навсегда осталось у %d человек, "
        "которые пользовались ботом раньше",
        granted,
    )
    return granted


async def stats(session: AsyncSession) -> dict:
    """Сводка для владельца: сколько людей и денег."""
    async def count(*conditions) -> int:
        stmt = select(func.count()).select_from(Subscription)
        for condition in conditions:
            stmt = stmt.where(condition)
        return int((await session.execute(stmt)).scalar_one())

    month_ago = now() - timedelta(days=30)
    revenue = int(
        (await session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.paid_at >= month_ago, Payment.refunded.is_(False)
            )
        )).scalar_one()
    )
    payers = int(
        (await session.execute(
            select(func.count(func.distinct(Payment.user_id)))
        )).scalar_one()
    )

    return {
        "total": await count(),
        # Вечный доступ считаем отдельно: это не выручка, а обещание,
        # данное тем, кто пришёл раньше оплаты.
        "active": await count(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now(),
            Subscription.lifetime.is_(False),
        ),
        "lifetime": await count(Subscription.lifetime.is_(True)),
        "trial": await count(
            Subscription.status == SubscriptionStatus.TRIAL, Subscription.expires_at > now()
        ),
        "expired": await count(
            Subscription.expires_at <= now(), Subscription.lifetime.is_(False)
        ),
        "recurring": await count(Subscription.is_recurring.is_(True)),
        "payers": payers,
        "stars_30d": revenue,
    }
