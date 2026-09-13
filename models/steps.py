"""Шаги за день.

Одна строка на человека и день, а не запись на каждое движение: телефон уже
посчитал шаги, и приложению остаётся запомнить итог. Человек может внести
число несколько раз за день — оно просто уточняется.

Почему число вносится руками, а не читается само. Мини-приложение внутри
Telegram не имеет доступа ни к «Здоровью» на айфоне, ни к датчику шагов:
это умеет только отдельное приложение, установленное из магазина. Поэтому
источник помечаем — если однажды появится другой, старые записи не придётся
угадывать.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Date, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class StepLog(Base):
    """Шаги за один день."""

    __tablename__ = "step_log"
    __table_args__ = (
        UniqueConstraint("user_id", "day", name="uq_step_log_user_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # День местный, а не UTC: шаги считаются по календарю человека.
    day: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # «manual» — внёс человек. Другого источника пока не бывает.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


__all__ = ["StepLog"]
