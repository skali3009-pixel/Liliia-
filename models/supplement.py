"""Витамины, добавки и лекарства: список пользователя и история приёма."""

from __future__ import annotations

import enum
from datetime import datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.user import User


class ScheduleTypeEnum(str, enum.Enum):
    DAILY = "daily"          # каждый день
    WEEKDAYS = "weekdays"    # по дням недели: «пн, ср, пт»
    INTERVAL = "interval"    # раз в N дней


class Supplement(Base):
    """Препарат в списке пользователя: что принимать и по какому графику."""

    __tablename__ = "supplements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Свободный текст: «5000 МЕ», «1 таблетка», «2 капсулы».
    dose: Mapped[str | None] = mapped_column(String(60), nullable=True)

    schedule_type: Mapped[ScheduleTypeEnum] = mapped_column(
        Enum(ScheduleTypeEnum, name="schedule_type_enum"),
        default=ScheduleTypeEnum.DAILY,
        nullable=False,
    )
    # Для WEEKDAYS: номера дней через запятую, 0 = понедельник ("0,2,4").
    weekdays: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Для INTERVAL: раз в сколько дней (7 = раз в неделю).
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Во сколько напоминать (по часовому поясу пользователя).
    reminder_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="supplements")
    logs: Mapped[list["SupplementLog"]] = relationship(
        back_populates="supplement", cascade="all, delete-orphan"
    )


class SupplementLog(Base):
    """Факт приёма (или осознанного пропуска) препарата."""

    __tablename__ = "supplement_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    supplement_id: Mapped[int] = mapped_column(
        ForeignKey("supplements.id", ondelete="CASCADE"), index=True, nullable=False
    )

    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="supplement_logs")
    supplement: Mapped["Supplement"] = relationship(back_populates="logs")
