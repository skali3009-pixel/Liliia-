"""Дневник за сегодня прямо в чате.

Записать еду из переписки было можно, а посмотреть, что уже записано, — нет:
список жил только в приложении. Между тем «что я сегодня ела» — самый частый
вопрос дня, и ради него человека приходилось выгонять на другой экран.
Ошибочную запись оттуда же нельзя было и убрать.

Поэтому здесь список сегодняшних приёмов с итогом дня и удаление одним
нажатием. Правка веса осталась в приложении: в чате её пришлось бы делать
разговором из трёх сообщений, а это дольше, чем открыть экран.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db import get_session
from keyboards.main_menu import main_menu_keyboard
from models import Meal, User
from services.meals import delete_meal, get_today_totals, list_today_meals
from utils.meal_time import MEAL_TYPE_RU
from utils.timeframe import to_local

logger = logging.getLogger(__name__)
router = Router(name="diary")

CB_DROP = "diary_drop:"

# Больше этого в одном сообщении не показываем: длинный список кнопок в чате
# читается хуже, чем короткий, а двадцать приёмов пищи за день не бывает.
MAX_ROWS = 10

EMPTY = (
    "📖 Сегодня в дневнике пусто.\n\n"
    "Пришли фото еды или расскажи словами — запишу."
)

NOT_READY = "Сначала настроим профиль — напиши /start."


def render(meals: list[Meal], totals, user: User, timezone_name: str) -> str:
    """Список съеденного и итог дня — то же, что видно на «Ленте дня»."""
    lines = ["📖 Сегодня в дневнике:", ""]
    for meal in meals[-MAX_ROWS:]:
        when = to_local(meal.logged_at, timezone_name).strftime("%H:%M")
        kind = MEAL_TYPE_RU.get(meal.meal_type, "") if meal.meal_type else ""
        label = f" · {kind}" if kind else ""
        lines.append(f"{when}{label} — {meal.name}, {round(meal.calories)} ккал")

    if len(meals) > MAX_ROWS:
        lines.append(f"…и ещё {len(meals) - MAX_ROWS} — все видно в приложении.")

    norm = user.daily_calories or 0
    lines += ["", f"🔥 Всего {round(totals.calories)}"
                  + (f" из {norm} ккал" if norm else " ккал")]
    lines.append(f"🥩 Б {round(totals.protein_g)} · 🥑 Ж {round(totals.fat_g)} · "
                 f"🍚 У {round(totals.carbs_g)} · 🥦 {round(totals.fiber_g)} г")
    return "\n".join(lines)


def drop_keyboard(meals: list[Meal]) -> InlineKeyboardMarkup:
    """По кнопке на приём: удалить ошибочную запись из чата — одно нажатие."""
    builder = InlineKeyboardBuilder()
    for meal in meals[-MAX_ROWS:]:
        name = meal.name if len(meal.name) <= 22 else meal.name[:21] + "…"
        builder.button(text=f"✕ {name}", callback_data=f"{CB_DROP}{meal.id}")
    builder.adjust(1)
    return builder.as_markup()


async def _show(target: Message, user_id: int, *, edit: bool = False) -> None:
    async with get_session() as session:
        user = await session.get(User, user_id)
        if user is None or not user.onboarding_completed:
            await target.answer(NOT_READY)
            return

        tz = user.timezone
        meals = await list_today_meals(session, user_id, timezone_name=tz)
        totals = await get_today_totals(session, user_id, timezone_name=tz)

    if not meals:
        if edit:
            await target.edit_text(EMPTY)
        else:
            await target.answer(EMPTY, reply_markup=main_menu_keyboard())
        return

    text = render(meals, totals, user, tz)
    keyboard = drop_keyboard(meals)
    if edit:
        await target.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


@router.message(Command("day"))
async def show_day(message: Message) -> None:
    await _show(message, message.from_user.id)


@router.callback_query(F.data.startswith(CB_DROP))
async def drop_meal(callback: CallbackQuery) -> None:
    try:
        meal_id = int(callback.data.removeprefix(CB_DROP))
    except ValueError:
        await callback.answer("Не понимаю, что убрать", show_alert=True)
        return

    async with get_session() as session:
        meal = await session.get(Meal, meal_id)
        # Чужую запись удалить нельзя, даже зная её номер.
        if meal is None or meal.user_id != callback.from_user.id:
            await callback.answer("Этой записи уже нет", show_alert=True)
        else:
            await delete_meal(session, meal)
            await callback.answer("Убрала")

    await _show(callback.message, callback.from_user.id, edit=True)
