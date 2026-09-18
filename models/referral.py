"""Кто кого привёл. Отдельно от дружбы — и это главное здесь.

Дружба в приложении симметричная: две строки, по одной с каждой стороны, и
кто из двоих прислал ссылку, из неё уже не узнать. А ещё её разрывают —
кнопка «убрать из друзей» есть, и нажимают её по самым разным причинам.
Если считать приглашения по дружбе, то ссора двух подруг задним числом
отменяет награду, которую одна из них честно заработала месяц назад.

Поэтому связь «привела — пришла» живёт своей строкой, создаётся один раз и
не удаляется никогда. Награды отмечаются прямо здесь, датами: строка сама
помнит, за что уже заплачено, и второй раз за то же самое не заплатят.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, DateTime, ForeignKey, Integer, func)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Referral(Base):
    """Одна строка на приведённого человека."""

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Кого привели. Один раз и навсегда: человек приходит по чьей-то ссылке
    # однажды, и переписать это потом другой ссылкой нельзя — иначе награду
    # можно было бы перевесить на себя, попросив знакомую прислать ссылку
    # и нажав «Начать заново».
    invited_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )
    # Кто привёл. Не внешний ключ нарочно, как и в дружбе: удаление своих
    # данных одним человеком не должно стирать историю другого.
    inviter_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Когда начислено за то, что приведённая дошла до конца анкеты.
    signup_rewarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Когда начислено за её первую оплату.
    payment_rewarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
