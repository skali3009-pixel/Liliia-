"""Уведомления: чего человек хочет, что ему уже отправили и о чём просил помолчать.

Три таблицы, и каждая нужна по своей причине.

Настройки — потому что один рубильник «напоминания вкл/выкл» слишком груб:
человеку может быть нужна вода и не нужны итоги дня, и выбор между «всё» и
«ничего» он решает в пользу «ничего».

История — потому что без неё невозможно ничего из того, что отличает умное
уведомление от рассылки: ни дневной бюджет, ни остывание, ни «не повторяй
то же самое», ни ответ на вопрос, работает ли вообще хоть одно сообщение.

Просьба помолчать — потому что «Позже» обязано что-то менять. Кнопка,
которая ничего не делает, хуже отсутствия кнопки.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

# Категории. Человек отключает их по одной — это и есть список галочек
# в настройках приложения.
KIND_TURN = "turn"              # «твой ход» — главное сообщение
KIND_MEAL = "meal"              # дневник еды
KIND_WATER = "water"            # вода
KIND_MOVEMENT = "movement"      # движение и шаги
KIND_WORLD = "world"            # мир и события
KIND_EVENING = "evening"        # итоги дня
KIND_ACHIEVEMENT = "achievement"  # достижения

KINDS = (KIND_TURN, KIND_MEAL, KIND_WATER, KIND_MOVEMENT,
         KIND_WORLD, KIND_EVENING, KIND_ACHIEVEMENT)

# Насколько часто человек готов слышать бота.
PACE_MINIMAL = "minimal"
PACE_BALANCED = "balanced"
PACE_ACTIVE = "active"
PACES = (PACE_MINIMAL, PACE_BALANCED, PACE_ACTIVE)

# Чем закончилось сообщение. Пусто — пока ничем.
RESULT_ACTED = "acted"          # нажал кнопку прямо в сообщении
RESULT_OPENED = "opened"        # открыл приложение вскоре после
RESULT_SNOOZED = "snoozed"      # «позже»
RESULT_MUTED = "muted"          # «сегодня не надо»
# Самый сильный отрицательный ответ: после этого сообщения человек
# выключил категорию целиком.
RESULT_DISABLED = "disabled"


class NotificationPrefs(Base):
    """Что человек согласен получать. Одна строка на человека."""

    __tablename__ = "notification_prefs"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    # Категории. По умолчанию включено всё, кроме тех, что могут удивить:
    # мир и достижения человек включает сам, когда уже понял, что это такое.
    turn: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    water: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    movement: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    world: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    evening: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    achievement: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Тихие часы — в часах местного времени человека. Ночью пишет только то,
    # что он завёл себе сам: например, приём добавки в 23:30.
    quiet_from: Mapped[int] = mapped_column(Integer, default=23, nullable=False)
    quiet_to: Mapped[int] = mapped_column(Integer, default=7, nullable=False)

    pace: Mapped[str] = mapped_column(String(20), default=PACE_BALANCED, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


class NotificationLog(Base):
    """Что и когда отправили — и чем это закончилось.

    День хранится отдельно от времени отправки специально: бюджет считается
    по местным суткам человека, а не по UTC, и вычислять их заново на каждой
    проверке значило бы читать часовой пояс ради каждой строки.
    """

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Что именно предложили: water, protein, steps… Пустое — сообщение без
    # конкретного действия, вроде итогов дня.
    code: Mapped[str] = mapped_column(String(30), default="", nullable=False)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    day: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    # Какими словами сказано: имя набора формулировок и номер варианта,
    # например «water_almost#2». Без этого нельзя узнать, какие слова
    # работают: в истории осталось бы «писали про воду», а как именно —
    # неизвестно, и сравнивать нечего.
    variant: Mapped[str] = mapped_column(String(40), default="", nullable=False)

    # Пусто, пока человек ничего не сделал. «Ничего» — тоже ответ, и по нему
    # считается усталость: сообщения, на которые не реагируют, должны
    # становиться реже сами.
    result: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    result_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NotificationSnooze(Base):
    """«Позже» и «сегодня не надо» — по одной строке на категорию."""

    __tablename__ = "notification_snooze"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_snooze_user_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "KINDS", "KIND_ACHIEVEMENT", "KIND_EVENING", "KIND_MEAL", "KIND_MOVEMENT",
    "KIND_TURN", "KIND_WATER", "KIND_WORLD",
    "PACES", "PACE_ACTIVE", "PACE_BALANCED", "PACE_MINIMAL",
    "RESULT_ACTED", "RESULT_DISABLED", "RESULT_MUTED", "RESULT_OPENED",
    "RESULT_SNOOZED",
    "NotificationLog", "NotificationPrefs", "NotificationSnooze",
]
