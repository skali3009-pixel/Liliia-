"""Durable migration delivery and joining the replacement bot."""
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class BotMigrationContact(Base):
    __tablename__ = "bot_migration_contacts"
    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery: Mapped[str | None] = mapped_column(String(24))
    message_id: Mapped[int | None] = mapped_column(Integer)
    error_kind: Mapped[str | None] = mapped_column(String(80))
