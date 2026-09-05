"""Карточка профиля и её правка прямо из бота.

Анкету заполняют один раз, а меняется всё: цель, режим тренировок, питание,
вес мечты. Раньше единственным способом что-то поправить было начать заново —
и вместе с анкетой человек терял дневник. Теперь каждое поле правится с самой
карточки, а норма КБЖУ пересчитывается сразу, чтобы не есть по старой цифре.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import get_session
from keyboards.main_menu import (MENU_ADD_MEAL, MENU_PROFILE, MENU_PROGRESS, MENU_WATER,
                                 MENU_WHAT_TO_EAT, MENU_WORKOUT)
from keyboards.onboarding import activity_keyboard, diet_type_keyboard, goal_keyboard
from keyboards.profile import (CB_BACK, CB_EDIT, CB_REMINDERS, edit_menu_keyboard,
                               with_back)
from models import User
from services import profile as profile_service
from states.profile import ProfileStates
from utils.parsing import parse_float, parse_int

logger = logging.getLogger(__name__)
router = Router(name="profile")

GENDER_RU = {"male": "мужской", "female": "женский"}
ACTIVITY_RU = {
    "sedentary": "сидячий образ жизни",
    "light": "лёгкая",
    "moderate": "умеренная",
    "high": "высокая",
    "very_high": "очень высокая",
}
GOAL_RU = {
    "lose_weight": "похудение",
    "maintain": "поддержание",
    "gain_mass": "набор массы",
    "recomposition": "рельеф",
}
DIET_RU = {
    "regular": "обычное",
    "vegan": "веган",
    "vegetarian": "вегетарианское",
    "gluten_free": "без глютена",
}

# Что спрашиваем текстом и в какое состояние при этом уходим.
TEXT_FIELDS = {
    "target_weight": (
        ProfileStates.target_weight,
        "Какой вес хочешь в итоге, кг? Например: 62",
    ),
    "height": (ProfileStates.height, "Какой у тебя рост, см? Например: 172"),
    "age": (ProfileStates.age, "Сколько тебе полных лет?"),
    "allergies": (
        ProfileStates.allergies,
        "Что тебе нельзя? Перечисли через запятую — или напиши «нет».",
    ),
}

CHOICE_FIELDS = {
    "goal": (goal_keyboard, "Какая у тебя цель?"),
    "activity": (activity_keyboard, "Какой у тебя уровень активности?"),
    "diet": (diet_type_keyboard, "Тип питания:"),
}

CANCEL_WORDS = {"отмена", "назад", "/cancel"}

MENU_TEXTS = {MENU_ADD_MEAL, MENU_WATER, MENU_WORKOUT, MENU_PROGRESS,
              MENU_WHAT_TO_EAT, MENU_PROFILE}

NOT_READY = "Профиль ещё не настроен. Напиши /start."


def _enum_ru(value, mapping: dict[str, str]) -> str:
    """Значение анкеты по-русски; неизвестное показываем как есть."""
    if value is None:
        return "—"
    raw = getattr(value, "value", value)
    return mapping.get(raw, str(raw))


def norms_line(user: User) -> str:
    return (
        f"🔥 Норма: {user.daily_calories or '—'} ккал | "
        f"Б {user.daily_protein_g or '—'} / Ж {user.daily_fat_g or '—'} / "
        f"У {user.daily_carbs_g or '—'} г\n"
        f"🥦 Клетчатка: {user.daily_fiber_g or '—'} г\n"
        f"💧 Вода: {user.daily_water_ml or '—'} мл"
    )


def profile_text(user: User) -> str:
    weight = f"{user.current_weight_kg:.1f}" if user.current_weight_kg else "—"
    target = f"{user.target_weight_kg:.1f}" if user.target_weight_kg else "—"
    height = f"{user.height_cm:.0f}" if user.height_cm else "—"
    return (
        "⚙️ Твой профиль:\n\n"
        f"Пол: {_enum_ru(user.gender, GENDER_RU)}\n"
        f"Возраст: {user.age or '—'}\n"
        f"Рост: {height} см\n"
        f"Вес: {weight} кг → цель {target} кг\n"
        f"Активность: {_enum_ru(user.activity_level, ACTIVITY_RU)}\n"
        f"Цель: {_enum_ru(user.goal, GOAL_RU)}\n"
        f"Питание: {_enum_ru(user.diet_type, DIET_RU)}\n"
        f"Аллергии: {user.allergies or 'нет'}\n"
        f"Напоминания: {'включены' if user.reminders_enabled else 'выключены'}\n\n"
        f"{norms_line(user)}\n\n"
        "Что-то изменилось? Поправь кнопками ниже 👇"
    )


async def _load(user_id: int) -> User | None:
    async with get_session() as session:
        user = await session.get(User, user_id)
    return user if user and user.onboarding_completed else None


async def _show_card(message: Message, user: User, *, edit: bool = False) -> None:
    """Карточка всегда одна и та же — правка обновляет её на месте."""
    text = profile_text(user)
    keyboard = edit_menu_keyboard(reminders_on=user.reminders_enabled)
    if edit:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
            return
    await message.answer(text, reply_markup=keyboard)


@router.message(StateFilter(ProfileStates), F.text.in_(MENU_TEXTS))
async def leave_editing(message: Message, state: FSMContext) -> None:
    """Кнопка меню важнее недописанного ответа.

    Без этого человек, начавший менять рост и ушедший в «Воду», остаётся в
    состоянии правки: следующая фраза молча уедет в поле профиля.
    """
    await state.clear()
    raise SkipHandler


@router.message(F.text == MENU_PROFILE)
async def show_profile(message: Message, state: FSMContext) -> None:
    # Человек мог уйти из недописанного ответа обратно в меню — не держим его.
    await state.clear()
    user = await _load(message.from_user.id)
    if user is None:
        await message.answer(NOT_READY)
        return
    await _show_card(message, user)


@router.callback_query(F.data.startswith(CB_EDIT))
async def open_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.removeprefix(CB_EDIT)
    user = await _load(callback.from_user.id)
    if user is None:
        await callback.answer(NOT_READY, show_alert=True)
        return

    if field in CHOICE_FIELDS:
        keyboard, question = CHOICE_FIELDS[field]
        await state.clear()
        await callback.message.edit_text(
            question, reply_markup=with_back(keyboard(prefix="prof"))
        )
        await callback.answer()
        return

    if field in TEXT_FIELDS:
        step, question = TEXT_FIELDS[field]
        await state.set_state(step)
        await callback.message.edit_text(f"{question}\n\n(или напиши «отмена»)")
        await callback.answer()
        return

    logger.warning("Неизвестное поле профиля: %s", field)
    await callback.answer()


@router.callback_query(F.data == CB_REMINDERS)
async def switch_reminders(callback: CallbackQuery) -> None:
    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None or not user.onboarding_completed:
            await callback.answer(NOT_READY, show_alert=True)
            return
        enabled = await profile_service.toggle_reminders(session, user)

    await _show_card(callback.message, user, edit=True)
    await callback.answer(
        "Напоминания включены" if enabled else "Больше не напоминаю"
    )


@router.callback_query(F.data == CB_BACK)
async def back_to_card(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = await _load(callback.from_user.id)
    if user is None:
        await callback.answer(NOT_READY, show_alert=True)
        return
    await _show_card(callback.message, user, edit=True)
    await callback.answer()


async def _apply_choice(callback: CallbackQuery, field: str) -> None:
    value = callback.data.split(":", 1)[1]
    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None or not user.onboarding_completed:
            await callback.answer(NOT_READY, show_alert=True)
            return
        setter = getattr(profile_service, f"set_{field}")
        try:
            recalculated = await setter(session, user, value)
        except ValueError:
            logger.warning("Недопустимое значение %s для поля %s", value, field)
            await callback.answer("Не понял вариант, попробуй ещё раз", show_alert=True)
            return

    await _show_card(callback.message, user, edit=True)
    await callback.answer("Норма пересчитана" if recalculated else "Сохранено")


@router.callback_query(F.data.startswith("prof_goal:"))
async def choose_goal(callback: CallbackQuery) -> None:
    await _apply_choice(callback, "goal")


@router.callback_query(F.data.startswith("prof_activity:"))
async def choose_activity(callback: CallbackQuery) -> None:
    await _apply_choice(callback, "activity")


@router.callback_query(F.data.startswith("prof_diet:"))
async def choose_diet(callback: CallbackQuery) -> None:
    await _apply_choice(callback, "diet")


async def _cancelled(message: Message, state: FSMContext) -> bool:
    if (message.text or "").strip().lower() not in CANCEL_WORDS:
        return False
    await state.clear()
    user = await _load(message.from_user.id)
    if user is not None:
        await _show_card(message, user)
    return True


async def _persist(message: Message, state: FSMContext, apply) -> None:
    """Сохранить одно поле и снова показать карточку."""
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None or not user.onboarding_completed:
            await state.clear()
            await message.answer(NOT_READY)
            return
        await apply(session, user)
    await state.clear()
    await _show_card(message, user)


@router.message(ProfileStates.target_weight, F.text)
async def save_target_weight(message: Message, state: FSMContext) -> None:
    if await _cancelled(message, state):
        return
    value = parse_float(message.text)
    if not profile_service.valid_target(value):
        await message.answer(
            f"Введи вес числом от {profile_service.MIN_TARGET_KG:.0f} до "
            f"{profile_service.MAX_TARGET_KG:.0f} кг, например: 62"
        )
        return
    await _persist(
        message,
        state,
        lambda session, user: profile_service.set_target_weight(session, user, value),
    )


@router.message(ProfileStates.height, F.text)
async def save_height(message: Message, state: FSMContext) -> None:
    if await _cancelled(message, state):
        return
    value = parse_float(message.text)
    if not profile_service.valid_height(value):
        await message.answer(
            f"Введи рост числом от {profile_service.MIN_HEIGHT_CM:.0f} до "
            f"{profile_service.MAX_HEIGHT_CM:.0f} см, например: 172"
        )
        return
    await _persist(
        message,
        state,
        lambda session, user: profile_service.set_height(session, user, value),
    )


@router.message(ProfileStates.age, F.text)
async def save_age(message: Message, state: FSMContext) -> None:
    if await _cancelled(message, state):
        return
    value = parse_int(message.text)
    if not profile_service.valid_age(value):
        await message.answer(
            f"Введи возраст числом от {profile_service.MIN_AGE} до "
            f"{profile_service.MAX_AGE}, например: 28"
        )
        return
    await _persist(
        message,
        state,
        lambda session, user: profile_service.set_age(session, user, value),
    )


@router.message(ProfileStates.allergies, F.text)
async def save_allergies(message: Message, state: FSMContext) -> None:
    if await _cancelled(message, state):
        return
    await _persist(
        message,
        state,
        lambda session, user: profile_service.set_allergies(session, user, message.text),
    )
