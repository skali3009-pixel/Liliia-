"""Что человек уже наготовил и когда.

Справочник заготовок в приложении есть давно, но он общий: там написано,
что борщ хранится три дня, а не что борщ есть у тебя в холодильнике. Без
этого «использовать заготовки при подборе» — пустые слова: непонятно,
из чего собирать.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class UserPrep(Base):
    """Отметка «я это приготовила» с датой."""

    __tablename__ = "user_preps"
    __table_args__ = (
        UniqueConstraint("user_id", "prep_code", name="uq_user_preps_user_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Код из справочника заготовок, а не название: название можно поправить.
    prep_code: Mapped[str] = mapped_column(String(60), nullable=False)
    made_on: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["UserPrep"]
