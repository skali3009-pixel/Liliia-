"""Приёмы пищи: результат фото-распознавания / ручного ввода."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.user import User


class MealTypeEnum(str, enum.Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class MealSourceEnum(str, enum.Enum):
    PHOTO = "photo"       # фото + Claude vision
    TEXT = "text"         # текстовое описание
    VOICE = "voice"       # голосовое (Whisper)
    BARCODE = "barcode"   # штрихкод / поиск по базе продуктов


class Meal(Base):
    """Один залогированный приём пищи (блюдо/продукт)."""

    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    meal_type: Mapped[MealTypeEnum | None] = mapped_column(
        Enum(MealTypeEnum, name="meal_type_enum"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    calories: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    source: Mapped[MealSourceEnum] = mapped_column(
        Enum(MealSourceEnum, name="meal_source_enum"), default=MealSourceEnum.TEXT, nullable=False
    )
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="meals")
