"""Inline-клавиатуры для шагов онбординга."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from models import DietTypeEnum, GenderEnum
from utils.formulas import ActivityLevel, Goal

GENDER_LABELS: dict[GenderEnum, str] = {
    GenderEnum.MALE: "👨 Мужской",
    GenderEnum.FEMALE: "👩 Женский",
}


def gender_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for gender, label in GENDER_LABELS.items():
        builder.button(text=label, callback_data=f"onb_gender:{gender.value}")
    builder.adjust(2)
    return builder.as_markup()


ACTIVITY_LABELS: dict[ActivityLevel, str] = {
    ActivityLevel.SEDENTARY: "🛋️ Сидячий образ жизни",
    ActivityLevel.LIGHT: "🚶 Лёгкая (1-3 трен/нед)",
    ActivityLevel.MODERATE: "🏃 Умеренная (3-5 трен/нед)",
    ActivityLevel.HIGH: "🏋️ Высокая (6-7 трен/нед)",
    ActivityLevel.VERY_HIGH: "🔥 Очень высокая (спорт + физ. работа)",
}


def activity_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for level, label in ACTIVITY_LABELS.items():
        builder.button(text=label, callback_data=f"onb_activity:{level.value}")
    builder.adjust(1)
    return builder.as_markup()


GOAL_LABELS: dict[Goal, str] = {
    Goal.LOSE_WEIGHT: "📉 Похудение",
    Goal.MAINTAIN: "⚖️ Поддержание",
    Goal.GAIN_MASS: "📈 Набор массы",
    Goal.RECOMPOSITION: "💎 Рельеф",
}


def goal_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for goal, label in GOAL_LABELS.items():
        builder.button(text=label, callback_data=f"onb_goal:{goal.value}")
    builder.adjust(1)
    return builder.as_markup()


DIET_LABELS: dict[DietTypeEnum, str] = {
    DietTypeEnum.REGULAR: "🍽️ Обычное",
    DietTypeEnum.VEGAN: "🌱 Веган",
    DietTypeEnum.VEGETARIAN: "🥦 Вегетарианское",
    DietTypeEnum.GLUTEN_FREE: "🌾 Без глютена",
}


def diet_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for diet, label in DIET_LABELS.items():
        builder.button(text=label, callback_data=f"onb_diet:{diet.value}")
    builder.adjust(1)
    return builder.as_markup()
