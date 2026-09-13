"""Женский календарь: когда начались месячные.

Хранится ровно одно — день начала. Всё остальное считается из него:
какой сегодня день цикла, какая фаза, какой длины циклы были раньше и
когда, скорее всего, начнутся следующие.

Почему только начало. День окончания женщины отмечают заметно реже —
начало помнят все, конец многие пропускают, — и календарь, который без
него не работает, перестаёт работать у большинства. Конец можно указать,
но он не обязателен.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class CycleLog(Base):
    __tablename__ = "cycle_log"
    __table_args__ = (
        UniqueConstraint("user_id", "started_on", name="uq_cycle_user_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True,
        nullable=False,
    )
    started_on: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    # Необязателен: конец отмечают далеко не все.
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
