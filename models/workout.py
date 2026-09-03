"""Справочник тренировок/упражнений и лог их выполнения пользователем."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from models.user import GoalEnum

if TYPE_CHECKING:
    from models.user import User


class LocationEnum(str, enum.Enum):
    HOME = "home"
    GYM = "gym"


class LevelEnum(str, enum.Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class WorkoutTypeEnum(str, enum.Enum):
    STRENGTH = "strength"
    CARDIO = "cardio"


class Workout(Base):
    """Упражнение/тренировка из библиотеки (справочник, не привязан к юзеру).

    Подбирается по цели x локации x уровню — см. спецификацию раздела
    «Тренировки». MET-значение используется для расчёта потраченных калорий.
    """

    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    workout_type: Mapped[WorkoutTypeEnum] = mapped_column(
        Enum(WorkoutTypeEnum, name="workout_type_enum"), nullable=False
    )
    goal: Mapped[GoalEnum | None] = mapped_column(Enum(GoalEnum, name="goal_enum"), nullable=True)
    location: Mapped[LocationEnum] = mapped_column(
        Enum(LocationEnum, name="location_enum"), nullable=False
    )
    level: Mapped[LevelEnum] = mapped_column(Enum(LevelEnum, name="level_enum"), nullable=False)

    sets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rest_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    met_value: Mapped[float] = mapped_column(Float, nullable=False)
    demo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    workout_logs: Mapped[list["WorkoutLog"]] = relationship(back_populates="workout")


class WorkoutLog(Base):
    """Факт выполнения тренировки/упражнения пользователем."""

    __tablename__ = "workout_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), index=True, nullable=False
    )

    sets_done: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reps_done: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories_burned: Mapped[float | None] = mapped_column(Float, nullable=True)

    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="workout_logs")
    workout: Mapped["Workout"] = relationship(back_populates="workout_logs")
