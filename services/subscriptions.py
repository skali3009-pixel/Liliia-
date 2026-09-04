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
from models import Payment, Subscription, SubscriptionSource, SubscriptionStatus

logger = logging.getLogger(__name__)


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
    )
    return list((await session.execute(stmt)).scalars())


async def mark_warned(session: AsyncSession, subscription: Subscription) -> None:
    subscription.warned_at = now()
    await session.commit()


async def grandfather_existing(session: AsyncSession, *, days: int = 30) -> int:
    """Дать доступ тем, кто пользовался ботом до появления подписки.

    Люди уже вели дневник — закрывать им бота одним обновлением нечестно.
    Выполняется один раз: у кого запись о подписке уже есть, того не трогаем.
    """
    from models import User

    stmt = (
        select(User.id)
        .outerjoin(Subscription, Subscription.user_id == User.id)
        .where(User.onboarding_completed.is_(True), Subscription.id.is_(None))
    )
    user_ids = list((await session.execute(stmt)).scalars())
    if not user_ids:
        return 0

    expires = now() + timedelta(days=days)
    for user_id in user_ids:
        session.add(
            Subscription(
                user_id=user_id,
                status=SubscriptionStatus.ACTIVE,
                source=SubscriptionSource.MANUAL,
                expires_at=expires,
                trial_used=True,
            )
        )
    await session.commit()
    logger.info("Доступ на %d дней выдан %d прежним пользователям", days, len(user_ids))
    return len(user_ids)


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
        "active": await count(
            Subscription.status == SubscriptionStatus.ACTIVE, Subscription.expires_at > now()
        ),
        "trial": await count(
            Subscription.status == SubscriptionStatus.TRIAL, Subscription.expires_at > now()
        ),
        "expired": await count(Subscription.expires_at <= now()),
        "recurring": await count(Subscription.is_recurring.is_(True)),
        "payers": payers,
        "stars_30d": revenue,
    }
