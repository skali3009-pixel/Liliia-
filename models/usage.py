"""Расход на запросы к модели: сколько токенов и сколько это стоило.

Без такой таблицы счёт за месяц — сюрприз. С ней видно, куда уходят деньги,
можно поставить дневной потолок и ограничить одного человека, чтобы он не
съел бюджет за всех.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ApiUsage(Base):
    """Один платный запрос к модели."""

    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # Что делали: photo, text, voice, build. По этому полю видно, что дороже.
    kind: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # День считаем по серверному времени: бюджет общий, а не по часовым поясам.
    day: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_api_usage_day_user", "day", "user_id"),)


__all__ = ["ApiUsage"]
