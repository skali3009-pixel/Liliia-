"""Durable payment attempts, separate from the settled payment ledger."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class PlategaOrder(Base):
    __tablename__ = "platega_orders"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    transaction_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="CREATING")
    amount: Mapped[int] = mapped_column(Integer, default=490)
    days: Mapped[int] = mapped_column(Integer, default=30)
    url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_via: Mapped[str | None] = mapped_column(String(24))
    callback_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlategaCallback(Base):
    """Authenticated receipts only. Never store secrets or raw request bodies."""
    __tablename__ = "platega_callbacks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(36), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(24), default="callback")
    result: Mapped[str] = mapped_column(String(24), default="RECEIVED")


class PlategaNotice(Base):
    """Outbox created in the same transaction as the access grant."""
    __tablename__ = "platega_notices"
    order_id: Mapped[str] = mapped_column(ForeignKey("platega_orders.id"), primary_key=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(64))

