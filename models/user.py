"""Модель пользователя: анкета онбординга + рассчитанная суточная норма."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.achievement import Achievement
    from models.body import BodyMeasurement, ProgressPhoto
    from models.meal import Meal
    from models.supplement import Supplement, SupplementLog
    from models.water import WaterLog
    from models.workout import WorkoutLog


class GenderEnum(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


class ActivityLevelEnum(str, enum.Enum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class GoalEnum(str, enum.Enum):
    LOSE_WEIGHT = "lose_weight"
    MAINTAIN = "maintain"
    GAIN_MASS = "gain_mass"
    RECOMPOSITION = "recomposition"


class DietTypeEnum(str, enum.Enum):
    REGULAR = "regular"
    VEGAN = "vegan"
    VEGETARIAN = "vegetarian"
    GLUTEN_FREE = "gluten_free"


class User(Base):
    """Пользователь Telegram-бота. id = Telegram user_id (не autoincrement)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Метка из ссылки-приглашения: t.me/бот?start=МЕТКА — видно, кто откуда пришёл.
    referral: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Согласие с офертой и политикой данных: какая редакция принята и когда.
    # Пустая версия означает, что человек ещё не соглашался.
    legal_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    legal_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Реклама — отдельное добровольное согласие, на доступ не влияет.
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Анкета онбординга ---
    gender: Mapped[GenderEnum | None] = mapped_column(
        Enum(GenderEnum, name="gender_enum"), nullable=True
    )
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_level: Mapped[ActivityLevelEnum | None] = mapped_column(
        Enum(ActivityLevelEnum, name="activity_level_enum"), nullable=True
    )
    goal: Mapped[GoalEnum | None] = mapped_column(Enum(GoalEnum, name="goal_enum"), nullable=True)
    diet_type: Mapped[DietTypeEnum] = mapped_column(
        Enum(DietTypeEnum, name="diet_type_enum"), default=DietTypeEnum.REGULAR, nullable=False
    )
    # Аллергии/непереносимости — свободный текст через запятую (MVP).
    allergies: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Часовой пояс в формате IANA («Europe/Moscow»): по нему считаются сутки
    # в дневнике и время напоминаний.
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)

    # --- Рассчитанная суточная норма (формула Миффлина-Сан Жеора) ---
    daily_calories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_protein_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_fat_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_carbs_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Клетчатка — отдельная цель, в калорийность рациона не входит.
    daily_fiber_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_water_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)

    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    streak_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    meals: Mapped[list["Meal"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    water_logs: Mapped[list["WaterLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    workout_logs: Mapped[list["WorkoutLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    body_measurements: Mapped[list["BodyMeasurement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    progress_photos: Mapped[list["ProgressPhoto"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    achievements: Mapped[list["Achievement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    supplements: Mapped[list["Supplement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    supplement_logs: Mapped[list["SupplementLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
