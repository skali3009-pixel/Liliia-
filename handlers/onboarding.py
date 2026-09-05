"""Пошаговый онбординг (FSM): анкета пользователя → расчёт нормы КБЖУ и воды."""

from __future__ import annotations

import logging

import config
from aiogram import F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import get_session
from keyboards.main_menu import main_menu_keyboard
from keyboards.onboarding import (
    activity_keyboard,
    diet_type_keyboard,
    gender_keyboard,
    goal_keyboard,
)
from models import ActivityLevelEnum, DietTypeEnum, GenderEnum, GoalEnum, User
from handlers.legal import consent_keyboard, needs_consent, welcome_text
from services.profile import (
    MAX_AGE,
    MAX_HEIGHT_CM,
    MAX_WEIGHT_KG,
    MIN_AGE,
    MIN_HEIGHT_CM,
    MIN_WEIGHT_KG,
)
from services.subscriptions import check_access, ensure_trial
from states.onboarding import OnboardingStates
from utils.formulas import ActivityLevel, Gender, Goal, calculate_macros, daily_water_ml
from utils.parsing import parse_float, parse_int

logger = logging.getLogger(__name__)
router = Router(name="onboarding")

GENDER_RU = {GenderEnum.MALE.value: "мужской", GenderEnum.FEMALE.value: "женский"}


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    """Первое знакомство: заводим человека, выдаём пробный период, ведём в анкету.

    Метка из ссылки (t.me/бот?start=МЕТКА) сохраняется, чтобы было видно,
    из какого поста или рекламы пришёл человек.
    """
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None:
            user = User(id=message.from_user.id)
            session.add(user)

        user.username = message.from_user.username
        user.full_name = message.from_user.full_name
        if command.args and not user.referral:
            user.referral = command.args[:64]
        await session.commit()

        # Пробный период отсчитывается от первого «Привет», а не от конца анкеты.
        await ensure_trial(session, user.id)
        access = await check_access(session, user.id)
        completed = user.onboarding_completed
        ask_consent = await needs_consent(user)

    # Пока человек не согласился с условиями, дальше не идём.
    if ask_consent:
        await state.clear()
        await message.answer(welcome_text(), reply_markup=consent_keyboard(),
                             disable_web_page_preview=True)
        return

    if completed:
        greeting = "С возвращением! 👋 Чем займёмся сегодня?"
        if access.allowed and access.is_trial:
            greeting += f"\n\nПробный период: осталось {access.days_left} дн."
        await message.answer(greeting, reply_markup=main_menu_keyboard())
        return

    await state.clear()
    await begin_onboarding(message, state, message.from_user.id)


async def begin_onboarding(message: Message, state: FSMContext, user_id: int) -> None:
    """Начать анкету. Вызывается и из /start, и сразу после согласия."""
    async with get_session() as session:
        user = await session.get(User, user_id)
        completed = bool(user and user.onboarding_completed)

    if completed:
        await message.answer("С возвращением! 👋 Чем займёмся сегодня?",
                             reply_markup=main_menu_keyboard())
        return

    await state.set_state(OnboardingStates.gender)
    await message.answer(
        f"Настроим профиль — это 1-2 минуты.\n"
        f"Первые {config.TRIAL_DAYS} дней бесплатно.\n\n"
        "Укажи свой пол:",
        reply_markup=gender_keyboard(),
    )


@router.callback_query(OnboardingStates.gender, F.data.startswith("onb_gender:"))
async def process_gender(callback: CallbackQuery, state: FSMContext) -> None:
    gender_value = callback.data.split(":", 1)[1]
    await state.update_data(gender=gender_value)
    await state.set_state(OnboardingStates.age)
    await callback.message.edit_text(f"Пол: {GENDER_RU[gender_value]} ✅")
    await callback.message.answer("Сколько тебе полных лет?")
    await callback.answer()


@router.message(OnboardingStates.age, F.text)
async def process_age(message: Message, state: FSMContext) -> None:
    age = parse_int(message.text)
    if age is None or not (MIN_AGE <= age <= MAX_AGE):
        await message.answer(f"Введи возраст числом от {MIN_AGE} до {MAX_AGE}, например: 28")
        return
    await state.update_data(age=age)
    await state.set_state(OnboardingStates.height)
    await message.answer("Какой у тебя рост, см? Например: 172")


@router.message(OnboardingStates.height, F.text)
async def process_height(message: Message, state: FSMContext) -> None:
    height = parse_float(message.text)
    if height is None or not (MIN_HEIGHT_CM <= height <= MAX_HEIGHT_CM):
        await message.answer(
            f"Введи рост числом от {MIN_HEIGHT_CM:.0f} до {MAX_HEIGHT_CM:.0f} см, например: 172"
        )
        return
    await state.update_data(height_cm=height)
    await state.set_state(OnboardingStates.current_weight)
    await message.answer("Какой у тебя текущий вес, кг? Например: 68.5")


@router.message(OnboardingStates.current_weight, F.text)
async def process_current_weight(message: Message, state: FSMContext) -> None:
    weight = parse_float(message.text)
    if weight is None or not (MIN_WEIGHT_KG <= weight <= MAX_WEIGHT_KG):
        await message.answer(
            f"Введи вес числом от {MIN_WEIGHT_KG:.0f} до {MAX_WEIGHT_KG:.0f} кг, например: 68.5"
        )
        return
    await state.update_data(current_weight_kg=weight)
    await state.set_state(OnboardingStates.target_weight)
    await message.answer("А какой вес хочешь в итоге, кг? Например: 62")


@router.message(OnboardingStates.target_weight, F.text)
async def process_target_weight(message: Message, state: FSMContext) -> None:
    weight = parse_float(message.text)
    if weight is None or not (MIN_WEIGHT_KG <= weight <= MAX_WEIGHT_KG):
        await message.answer(
            f"Введи вес числом от {MIN_WEIGHT_KG:.0f} до {MAX_WEIGHT_KG:.0f} кг, например: 62"
        )
        return
    await state.update_data(target_weight_kg=weight)
    await state.set_state(OnboardingStates.activity_level)
    await message.answer("Какой у тебя уровень активности?", reply_markup=activity_keyboard())


@router.callback_query(OnboardingStates.activity_level, F.data.startswith("onb_activity:"))
async def process_activity(callback: CallbackQuery, state: FSMContext) -> None:
    activity_value = callback.data.split(":", 1)[1]
    await state.update_data(activity_level=activity_value)
    await state.set_state(OnboardingStates.goal)
    await callback.message.edit_text("Уровень активности сохранён ✅")
    await callback.message.answer("Какая у тебя цель?", reply_markup=goal_keyboard())
    await callback.answer()


@router.callback_query(OnboardingStates.goal, F.data.startswith("onb_goal:"))
async def process_goal(callback: CallbackQuery, state: FSMContext) -> None:
    goal_value = callback.data.split(":", 1)[1]
    await state.update_data(goal=goal_value)
    await state.set_state(OnboardingStates.diet_type)
    await callback.message.edit_text("Цель сохранена ✅")
    await callback.message.answer("Тип питания:", reply_markup=diet_type_keyboard())
    await callback.answer()


@router.callback_query(OnboardingStates.diet_type, F.data.startswith("onb_diet:"))
async def process_diet_type(callback: CallbackQuery, state: FSMContext) -> None:
    diet_value = callback.data.split(":", 1)[1]
    await state.update_data(diet_type=diet_value)
    await state.set_state(OnboardingStates.allergies)
    await callback.message.edit_text("Тип питания сохранён ✅")
    await callback.message.answer(
        "Есть ли аллергии или непереносимости? Перечисли через запятую (или напиши «нет»):"
    )
    await callback.answer()


@router.message(OnboardingStates.allergies, F.text)
async def process_allergies(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    allergies = None if text.lower() in {"нет", "-", "none", "no"} else text
    await state.update_data(allergies=allergies)
    await _finish_onboarding(message, state)


async def _finish_onboarding(message: Message, state: FSMContext) -> None:
    data = await state.get_data()

    macros = calculate_macros(
        gender=Gender(data["gender"]),
        weight_kg=data["current_weight_kg"],
        height_cm=data["height_cm"],
        age_years=data["age"],
        activity_level=ActivityLevel(data["activity_level"]),
        goal=Goal(data["goal"]),
    )
    water_ml = daily_water_ml(
        weight_kg=data["current_weight_kg"],
        activity_level=ActivityLevel(data["activity_level"]),
    )

    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None:
            user = User(id=message.from_user.id)
            session.add(user)

        user.username = message.from_user.username
        user.full_name = message.from_user.full_name
        user.gender = GenderEnum(data["gender"])
        user.age = data["age"]
        user.height_cm = data["height_cm"]
        user.current_weight_kg = data["current_weight_kg"]
        user.target_weight_kg = data["target_weight_kg"]
        user.activity_level = ActivityLevelEnum(data["activity_level"])
        user.goal = GoalEnum(data["goal"])
        user.diet_type = DietTypeEnum(data["diet_type"])
        user.allergies = data.get("allergies")
        user.daily_calories = macros.calories
        user.daily_protein_g = macros.protein_g
        user.daily_fat_g = macros.fat_g
        user.daily_carbs_g = macros.carbs_g
        user.daily_fiber_g = macros.fiber_g
        user.daily_water_ml = water_ml
        user.onboarding_completed = True

        await session.commit()

    await state.clear()
    await message.answer(
        "Профиль настроен! 🎉\n\n"
        "Твоя суточная норма:\n"
        f"🔥 Калории: {macros.calories} ккал\n"
        f"🥩 Белки: {macros.protein_g} г\n"
        f"🥑 Жиры: {macros.fat_g} г\n"
        f"🍚 Углеводы: {macros.carbs_g} г\n"
        f"🥦 Клетчатка: {macros.fiber_g} г\n"
        f"💧 Вода: {water_ml} мл\n\n"
        "Дальше можно фотографировать еду, отмечать воду и тренироваться — "
        "жми на кнопки в меню 👇",
        reply_markup=main_menu_keyboard(),
    )
