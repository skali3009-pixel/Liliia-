"""Итог игрового дня: сколько опыта набрано и какие задания закрыты.

Одна строка на пользователя и дату. Сегодняшняя строка пересчитывается при
каждом открытии приложения (данные могли измениться), прошедшие остаются как
есть — по ним считаются стрик и общий опыт, не поднимая всю историю еды.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DayStat(Base):
    __tablename__ = "day_stats"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_day_stats_user_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    day: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Коды выполненных заданий через запятую — читаемо и не требует JSON-типа.
    quests_done: Mapped[str] = mapped_column(String(255), default="", nullable=False)
