"""Подписка на приложение и история платежей.

Доступ даёт не ссылка на бота (её всё равно перешлют), а активная подписка.
Пробный период выдаётся один раз: чтобы человек успел увидеть, за что платит.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column


from models.base import Base


class SubscriptionStatus(str, enum.Enum):
    TRIAL = "trial"        # бесплатный пробный период
    ACTIVE = "active"      # оплачено
    EXPIRED = "expired"    # срок вышел


class SubscriptionSource(str, enum.Enum):
    TRIAL = "trial"
    STARS = "stars"        # оплата звёздами Telegram
    MANUAL = "manual"      # выдана владельцем вручную


class Subscription(Base):
    """Одна запись на пользователя: текущий доступ и его срок."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status_enum"),
        default=SubscriptionStatus.TRIAL,
        nullable=False,
    )
    source: Mapped[SubscriptionSource] = mapped_column(
        Enum(SubscriptionSource, name="subscription_source_enum"),
        default=SubscriptionSource.TRIAL,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Telegram сам списывает раз в месяц, пока человек не отменит подписку.
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Пробный период даётся один раз за всё время.
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Когда предупреждали об окончании — чтобы не слать одно и то же дважды.
    warned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Payment(Base):
    """История оплат — для отчётности и возвратов."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    amount: Mapped[int] = mapped_column(Integer, nullable=False)          # в звёздах
    currency: Mapped[str] = mapped_column(String(10), default="XTR", nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)            # сколько дней куплено
    # Идентификатор платежа в Telegram — по нему делается возврат.
    charge_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    refunded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
