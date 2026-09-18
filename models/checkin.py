"""Состояние на момент времени: энергия, настроение, фокус, стресс, сон.

Отдельная таблица от еды: одно и то же сообщение («позавтракала и чувствую
себя бодрее») может дать и приём пищи, и отметку состояния, но живут они
своей жизнью — состояние можно записать и без еды.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Checkin(Base):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Всё необязательно: человек отмечает то, что заметил, а не анкету целиком.
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)      # 1..10
    focus: Mapped[int | None] = mapped_column(Integer, nullable=True)       # 1..10
    mood: Mapped[str | None] = mapped_column(String(30), nullable=True)     # спокойно, бодро…
    stress: Mapped[str | None] = mapped_column(String(20), nullable=True)   # низкий/средний/высокий
    sleep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
