"""Сколько раз нажимали каждую кнопку меню в чате.

Заведено на время испытаний, чтобы не гадать, чем люди пользуются, а
знать. Хранится не по нажатию, а сводкой: человек, кнопка, день и счётчик.
Так таблица не растёт бесконечно, и по ней сразу видно и число нажатий, и
число людей, которым кнопка вообще нужна.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ButtonPress(Base):
    __tablename__ = "button_press"
    __table_args__ = (
        UniqueConstraint("user_id", "button", "day", name="uq_button_user_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True,
        nullable=False,
    )
    # Имя кнопки как она подписана, без эмодзи: «Мой ход», «Вода».
    button: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    day: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
