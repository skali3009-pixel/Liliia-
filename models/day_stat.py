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
    # Что уже предлагали сегодня в карточке «Твой ход», через запятую.
    # Без этого один и тот же совет показывался бы весь день, и человек
    # перестал бы читать карточку вообще — вместе со всеми остальными советами.
    suggested: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Сколько мест мира было открыто в этот день. Нужно ровно для одного:
    # заметить, что сегодня открылось новое, и порадоваться вместе с человеком.
    world_open: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Кристаллы сверх заданий: событие мира и редкая находка. Отдельно от xp
    # потому, что xp пересчитывается по заданиям при каждом открытии экрана и
    # затёр бы любую добавку.
    bonus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # За что бонус уже начислен сегодня, через запятую: event, surprise.
    # Начисляем каждое ровно один раз в день.
    bonus_codes: Mapped[str] = mapped_column(String(60), default="", nullable=False)
