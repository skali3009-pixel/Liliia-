"""Служебные отметки самого приложения: что уже сделано один раз.

Некоторые вещи нельзя повторять при каждом запуске. Например, «в момент
включения платного доступа всем, кто уже был в боте, оставить его
бесплатным навсегда» — это разовое событие, и второй раз оно не должно
случиться никогда. Файл на диске для такого не годится: диск переустановят,
а база переедет вместе с резервной копией.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AppState(Base):
    """Пара «ключ — значение» на всё приложение."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
