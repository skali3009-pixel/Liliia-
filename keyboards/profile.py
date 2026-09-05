"""Кнопки карточки профиля: что именно человек хочет поменять."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

CB_EDIT = "prof_edit:"
CB_BACK = "prof_back"
CB_REMINDERS = "prof_reminders"

# Порядок не случайный: сверху то, что меняют чаще всего.
FIELD_LABELS: dict[str, str] = {
    "goal": "🎯 Цель",
    "target_weight": "⚖️ Вес цели",
    "activity": "🏃 Активность",
    "diet": "🍽️ Тип питания",
    "allergies": "🚫 Аллергии",
    "height": "📏 Рост",
    "age": "🎂 Возраст",
}


def edit_menu_keyboard(*, reminders_on: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field, label in FIELD_LABELS.items():
        builder.button(text=label, callback_data=f"{CB_EDIT}{field}")
    # Выключить напоминания должно быть так же легко, как их получать —
    # иначе единственный способ от них избавиться это удалить бота.
    builder.button(
        text="🔔 Напоминания: вкл" if reminders_on else "🔕 Напоминания: выкл",
        callback_data=CB_REMINDERS,
    )
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def with_back(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Любой список вариантов должен иметь выход без выбора."""
    rows = list(markup.inline_keyboard)
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=CB_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


__all__ = ["CB_BACK", "CB_EDIT", "CB_REMINDERS", "FIELD_LABELS", "edit_menu_keyboard",
           "with_back"]
