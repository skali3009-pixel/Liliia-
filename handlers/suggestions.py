"""Кнопка «Что съесть» в чате: подбор блюда под остаток нормы.

Показывает то же, что и приложение: блюда из меню Анастасии со значком и
блюда, собранные по её принципам, — без пометок. Всё КБЖУ посчитано по
справочнику, поэтому запись в дневник точная, а не «примерно».
"""

from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db import get_session
from keyboards.main_menu import MENU_WHAT_TO_EAT
from models import MealSourceEnum, Prep, User
from services.food_vision import FoodAnalysis
from services.meals import get_today_totals, save_meal
from services.menu import MEAL_RU, Offer, board
from utils.meal_time import guess_meal_type
from utils.timeframe import get_zone

logger = logging.getLogger(__name__)
router = Router(name="suggestions")

CB_EAT = "eat:"
CB_MEAL = "meal:"
CB_COOK = "cook:"
CB_RECIPE = "recipe:"

AUTHOR_MARK = "⭐"

# Предложенные варианты живут до перезапуска бота: класть их в базу ради
# одной кнопки ни к чему, а устаревший ключ обрабатывается отдельно.
_offered: dict[str, Offer] = {}


def _keyboard(key: str, *, with_recipe: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if with_recipe:
        builder.button(text="📖 Рецепт", callback_data=f"{CB_RECIPE}{key}")
    builder.button(text="✅ Съела это", callback_data=f"{CB_EAT}{key}")
    builder.adjust(2)
    return builder.as_markup()


def _meal_keyboard(active: str, *, no_cook: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, title in MEAL_RU.items():
        mark = "· " if code == active else ""
        builder.button(text=f"{mark}{title.capitalize()}", callback_data=f"{CB_MEAL}{code}")
    # Готовить негде — обычное состояние в дороге и на работе.
    builder.button(text=("· 🍳 Приготовлю" if not no_cook else "🍳 Приготовлю"),
                   callback_data=f"{CB_COOK}{active}:1")
    builder.button(text=("· 🛒 Без готовки" if no_cook else "🛒 Без готовки"),
                   callback_data=f"{CB_COOK}{active}:0")
    builder.adjust(4, 2)
    return builder.as_markup()


def offer_text(offer: Offer) -> str:
    mark = f" {AUTHOR_MARK}" if offer.author else ""
    lines = [
        f"🍽 {offer.name}{mark}",
        f"{round(offer.weight_g)} г · {round(offer.calories)} ккал · {offer.minutes} мин",
        f"Б {round(offer.protein_g)} · Ж {round(offer.fat_g)} · У {round(offer.carbs_g)} г",
    ]
    if offer.fiber_g:
        lines.append(f"🥦 Клетчатка {round(offer.fiber_g)} г")
    if offer.preps:
        lines.append(f"🥘 Из заготовок: {', '.join(offer.preps)}")
    if offer.reason:
        lines.append(f"\n💬 {offer.reason}")
    return "\n".join(lines)


def recipe_text(offer: Offer) -> str:
    mark = f" {AUTHOR_MARK}" if offer.author else ""
    lines = [f"📖 {offer.name}{mark}", ""]
    for part in offer.components or []:
        if part.get("seasoning"):
            lines.append(f"• {part['name']} — {part.get('raw') or 'по вкусу'}")
        else:
            lines.append(f"• {part['name']} — {part['grams']} г")
    if offer.instructions:
        lines += ["", offer.instructions]
    if offer.estimated:
        lines += ["", "⚖️ Порции подобраны — точных граммов в рецепте нет."]
    elif offer.notes:
        lines += ["", offer.notes]
    if offer.preps:
        lines += ["", f"🥘 Из заготовок: {', '.join(offer.preps)}"]
    return "\n".join(lines)


async def _show(message: Message, user_id: int, meal_type: str | None,
                no_cook: bool = False) -> None:
    async with get_session() as session:
        user = await session.get(User, user_id)
        if user is None or not user.onboarding_completed:
            await message.answer("Сначала настроим профиль — напиши /start.")
            return
        result = await board(session, user, meal_type=meal_type, no_cook=no_cook)

    header = [
        f"🍽 {result.meal_name.capitalize()} — около {result.budget} ккал",
        f"На сегодня осталось {result.left_calories} ккал",
        "",
        result.hint,
    ]
    if result.approximate:
        header.append("\nТочного варианта нет — вот что ближе всего.")
    await message.answer("\n".join(header),
                         reply_markup=_meal_keyboard(result.meal_type, no_cook=no_cook))

    if not result.offers:
        await message.answer(
            "Готовых наборов на такой бюджет нет — попробуй другой приём пищи."
            if no_cook else
            "На такой бюджет подходящего блюда нет. Попробуй другой приём пищи "
            "или загляни позже."
        )
        return

    for index, offer in enumerate(result.offers):
        key = f"{user_id}:{result.meal_type}:{int(no_cook)}:{index}"
        _offered[key] = offer
        await message.answer(
            offer_text(offer),
            reply_markup=_keyboard(key, with_recipe=bool(offer.components)),
        )


@router.message(F.text == MENU_WHAT_TO_EAT)
async def what_to_eat(message: Message) -> None:
    status = await message.answer("🔍 Подбираю…")
    try:
        await _show(message, message.from_user.id, None)
    finally:
        try:
            await status.delete()
        except Exception:  # noqa: BLE001 — сообщение могли удалить руками
            pass


@router.message(Command("preps"))
async def show_preps(message: Message) -> None:
    """Список заготовок со сроками хранения — прямо в чате."""
    from sqlalchemy import select

    async with get_session() as session:
        preps = (await session.execute(select(Prep).order_by(Prep.name))).scalars().all()

    if not preps:
        await message.answer("Справочник заготовок ещё не загружен.")
        return

    lines = ["🥘 Заготовки: приготовил один раз — ешь несколько дней\n"]
    for prep in preps:
        keep = " · ".join(filter(None, [
            f"❄️ {prep.fridge_days}" if prep.fridge_days else "",
            f"🧊 {prep.freezer_days}" if prep.freezer_days else "",
        ]))
        lines.append(f"• {prep.name}\n  {round(prep.kcal)} ккал в 100 г"
                     + (f" · {keep}" if keep else ""))
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith(CB_MEAL))
async def switch_meal(callback: CallbackQuery) -> None:
    meal = callback.data.removeprefix(CB_MEAL)
    await callback.answer()
    await _show(callback.message, callback.from_user.id, meal)


@router.callback_query(F.data.startswith(CB_COOK))
async def switch_cooking(callback: CallbackQuery) -> None:
    meal, flag = callback.data.removeprefix(CB_COOK).rsplit(":", 1)
    await callback.answer()
    await _show(callback.message, callback.from_user.id, meal or None, no_cook=flag == "0")


@router.callback_query(F.data.startswith(CB_RECIPE))
async def show_recipe(callback: CallbackQuery) -> None:
    offer = _offered.get(callback.data.removeprefix(CB_RECIPE))
    if offer is None:
        await callback.answer("Вариант устарел — подбери заново", show_alert=True)
        return
    await callback.message.answer(recipe_text(offer))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_EAT))
async def eat_suggestion(callback: CallbackQuery) -> None:
    key = callback.data.removeprefix(CB_EAT)
    offer = _offered.get(key)
    if offer is None:
        await callback.answer("Вариант устарел — подбери заново", show_alert=True)
        return

    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None:
            await callback.answer("Сначала настрой профиль: /start", show_alert=True)
            return

        await save_meal(
            session,
            user_id=user.id,
            analysis=FoodAnalysis(
                name=offer.name, weight_g=offer.weight_g, calories=offer.calories,
                protein_g=offer.protein_g, fat_g=offer.fat_g, carbs_g=offer.carbs_g,
                fiber_g=offer.fiber_g,
                # Состав известен до грамма — это не догадка распознавания.
                confidence="high", comment="",
            ),
            source=MealSourceEnum.TEXT,
            meal_type=guess_meal_type(datetime.now(get_zone(user.timezone))),
        )
        totals = await get_today_totals(session, user.id, timezone_name=user.timezone)

    _offered.pop(key, None)
    await callback.message.edit_text(
        f"{callback.message.text}\n\n✅ Записала. Сегодня: {round(totals.calories)} ккал"
    )
    await callback.answer("Записала")
