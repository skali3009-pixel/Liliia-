"""Команда: маленькая группа, которая ходит вместе.

Соревнование в приложении про еду устроено осторожно: таблиц по сброшенным
килограммам здесь нет и не будет — это соревнование по голоданию. Шаги —
другое дело. Обогнать друга можно только тем, что полезно обоим, поэтому
рейтинг здесь честный и уместный.

Команда одна на человека. Так «внутри команды» означает одно и то же для
всех её участников, и не приходится объяснять, в каком из пяти списков
человек сейчас первый.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, DateTime, ForeignKey, Integer, String, func)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Team(Base):
    """Группа людей, которые считают шаги вместе."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    # Короткий код: по нему вступают по ссылке. Сменить его — значит закрыть
    # старую ссылку, не распуская команду.
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TeamMember(Base):
    """Участие. Одно на человека: команда у каждого одна."""

    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["Team", "TeamMember"]
