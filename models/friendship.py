"""Друзья: связь между двумя людьми и приглашение по ссылке.

Что здесь важно понимать сразу: дружба в этом приложении не даёт доступа к
данным. Она даёт доступ к игровому слою — кристаллам, уровню, серии и
местам мира. Вес, замеры, фотографии, калории и еда не передаются между
людьми ни в каком виде: это медицинские данные, и человек делится ими с
приложением, а не со знакомыми.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Invite(Base):
    """Личная ссылка-приглашение. Одна на человека, можно обновить."""

    __tablename__ = "friend_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )
    # Короткий случайный код. Угадать его нельзя, а сменить можно в один шаг —
    # это и есть способ отозвать ссылку, которую отправили не туда.
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Friendship(Base):
    """Дружба. Хранится двумя строками — по одной с каждой стороны.

    Так проще всего: список друзей человека — это выборка по одному полю, а
    разрыв связи с любой стороны убирает обе строки.
    """

    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("user_id", "friend_id", name="uq_friendships_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    friend_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["Friendship", "Invite"]
