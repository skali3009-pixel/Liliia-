"""Незаконченный разговор: на каком он шаге и что уже сказано.

Раньше это жило только в памяти процесса, и всякий перезапуск бота стирал
всё разом. Человек фотографировал еду, отвлекался, возвращался к карточке
и жал «Сохранить» — а бот к тому времени уже обновился и не понимал, о чём
речь. Кнопка крутилась, пока Telegram не сдавался.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FsmState(Base):
    __tablename__ = "fsm_state"

    # Бот, чат, человек и «ветка» — одной строкой.
    key: Mapped[str] = mapped_column(String(160), primary_key=True)

    # Имя шага. Пусто — разговора нет, но данные могли остаться.
    state: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # Всё, что накопил разговор, — JSON-строкой. Схемы у него нет: у каждого
    # сценария свои поля, и заводить под них колонки значило бы менять базу
    # ради каждого нового вопроса.
    data: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
