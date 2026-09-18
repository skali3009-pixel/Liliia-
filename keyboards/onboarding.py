"""Inline-клавиатуры для шагов онбординга.

Те же самые списки нужны потом в редактировании профиля, поэтому у каждой
клавиатуры есть префикс callback-данных: онбординг слушает «onb_», профиль —
«prof_», и один и тот же выбор не срабатывает дважды в разных сценариях.
"""

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


def activity_keyboard(prefix: str = "onb") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for level, label in ACTIVITY_LABELS.items():
        builder.button(text=label, callback_data=f"{prefix}_activity:{level.value}")
    builder.adjust(1)
    return builder.as_markup()


GOAL_LABELS: dict[Goal, str] = {
    Goal.LOSE_WEIGHT: "📉 Похудение",
    Goal.MAINTAIN: "⚖️ Поддержание",
    Goal.GAIN_MASS: "📈 Набор массы",
    Goal.RECOMPOSITION: "💎 Рельеф",
}


def goal_keyboard(prefix: str = "onb") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for goal, label in GOAL_LABELS.items():
        builder.button(text=label, callback_data=f"{prefix}_goal:{goal.value}")
    builder.adjust(1)
    return builder.as_markup()


# Подписи объясняют разницу, а не только называют диету. Лилия, владелица
# бота, увидела «Веган» и «Вегетарианское» рядом и решила, что это одна
# кнопка продублировалась. Диеты разные — у вегана нет ни молока, ни яиц, —
# но если этого не видно хозяйке, то человеку в анкете не видно тем более.
# Кнопки идут по одной в строке, место для пояснения есть; длиннее делать
# нельзя — Telegram обрежет на узком экране.
DIET_LABELS: dict[DietTypeEnum, str] = {
    DietTypeEnum.REGULAR: "🍽️ Обычное — ем всё",
    DietTypeEnum.VEGAN: "🌱 Веган — ни мяса, ни молока",
    DietTypeEnum.VEGETARIAN: "🥦 Вегетарианское — без мяса",
    DietTypeEnum.GLUTEN_FREE: "🌾 Без глютена",
}


def diet_type_keyboard(prefix: str = "onb") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for diet, label in DIET_LABELS.items():
        builder.button(text=label, callback_data=f"{prefix}_diet:{diet.value}")
    builder.adjust(1)
    return builder.as_markup()
