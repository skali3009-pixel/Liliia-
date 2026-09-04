"""Добавление еды: фото → Claude vision → карточка с КБЖУ → ручная коррекция → сохранение."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import get_session
from keyboards.food import (
    CB_CANCEL,
    CB_LESS,
    CB_MORE,
    CB_SAVE,
    CB_WEIGHT,
    CB_WRONG_DISH,
    food_card_keyboard,
)
from keyboards.main_menu import MENU_ADD_MEAL, main_menu_keyboard
from models import MealSourceEnum, User
from services.food_vision import (
    CONFIDENCE_RU,
    FoodAnalysis,
    FoodNotRecognized,
    FoodRecognitionError,
    VisionNotConfigured,
    analyze_photo,
    analyze_text,
)
from services.gamification import sync_today
from services.meals import get_today_totals, list_today_meals, save_meal
from services.transcription import TranscriptionError, VoiceNotConfigured, transcribe
from services.water import today_total_ml
from states.food import FoodStates
from utils.meal_time import MEAL_TYPE_RU, guess_meal_type
from utils.parsing import parse_float
from utils.portions import MAX_WEIGHT_G, MIN_WEIGHT_G, adjust_weight, scale_nutrition
from utils.progress import format_remaining, render_progress_bar
from utils.timeframe import DEFAULT_TIMEZONE, get_zone

logger = logging.getLogger(__name__)
router = Router(name="food")

# Claude принимает изображения до 5 МБ; фото из Telegram обычно сильно меньше,
# но подстрахуемся понятным сообщением вместо ошибки API.
MAX_IMAGE_BYTES = 4_500_000

GENERIC_ERROR = (
    "Не получилось распознать блюдо — попробуй ещё раз или опиши его текстом.\n"
    "Например: «тарелка борща со сметаной и два куска бородинского»."
)


def _num(value: float) -> str:
    """Числа в карточке — без дробей: точность оценки этого не оправдывает."""
    return f"{round(value):g}"


def _render_card(analysis: FoodAnalysis, meal_type_label: str) -> str:
    confidence = CONFIDENCE_RU.get(analysis.confidence, analysis.confidence)
    lines = [
        f"🍽 {analysis.name}",
        f"⚖️ ~{_num(analysis.weight_g)} г · {meal_type_label}",
        "",
        f"🔥 {_num(analysis.calories)} ккал",
        f"🥩 Б {_num(analysis.protein_g)} · 🥑 Ж {_num(analysis.fat_g)} · "
        f"🍚 У {_num(analysis.carbs_g)} г",
        f"🥦 Клетчатка {_num(analysis.fiber_g)} г",
    ]
    if analysis.comment:
        lines += ["", f"💬 {analysis.comment}"]
    lines += [f"Уверенность: {confidence}"]
    return "\n".join(lines)


def _current_meal_label(timezone_name: str = DEFAULT_TIMEZONE) -> str:
    """Завтрак/обед/ужин определяем по местному времени пользователя."""
    return MEAL_TYPE_RU[guess_meal_type(datetime.now(get_zone(timezone_name)))]


async def _show_card(
    message: Message, state: FSMContext, analysis: FoodAnalysis, *, photo_file_id: str | None
) -> None:
    """Показать карточку распознавания и запомнить её для последующих правок."""
    card = await message.answer(
        _render_card(analysis, _current_meal_label()), reply_markup=food_card_keyboard()
    )
    await state.set_state(FoodStates.confirming)
    await state.update_data(
        analysis=analysis.to_dict(),
        photo_file_id=photo_file_id,
        card_message_id=card.message_id,
    )


async def _update_card(message: Message, state: FSMContext, analysis: FoodAnalysis) -> None:
    """Перерисовать существующую карточку после коррекции."""
    data = await state.get_data()
    card_message_id = data.get("card_message_id")
    await state.update_data(analysis=analysis.to_dict())

    if card_message_id is None:
        await _show_card(message, state, analysis, photo_file_id=data.get("photo_file_id"))
        return

    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=card_message_id,
            text=_render_card(analysis, _current_meal_label()),
            reply_markup=food_card_keyboard(),
        )
    except TelegramBadRequest as e:
        # Текст не изменился (например, модель дала тот же результат) — не ошибка.
        if "message is not modified" not in str(e):
            raise


async def _ensure_onboarded(message: Message) -> User | None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)

    if user is None or not user.onboarding_completed:
        await message.answer(
            "Сначала настроим профиль — без него не посчитать остаток по норме. Напиши /start."
        )
        return None
    return user


@router.message(F.text == MENU_ADD_MEAL)
async def start_adding_food(message: Message, state: FSMContext) -> None:
    if await _ensure_onboarded(message) is None:
        return

    await state.set_state(FoodStates.waiting_input)
    await message.answer(
        "Пришли фото блюда 📷 — распознаю и посчитаю КБЖУ.\n"
        "Или наговори голосовым 🎤, или напиши текстом: «омлет из трёх яиц с сыром»."
    )


@router.message(StateFilter(None, FoodStates), F.photo)
async def handle_food_photo(message: Message, state: FSMContext) -> None:
    """Фото вне сценариев (или на любом шаге добавления еды) — это еда.

    Во время онбординга состояние принадлежит другой группе, поэтому анкету
    этот хендлер не перехватывает.
    """
    if await _ensure_onboarded(message) is None:
        return

    photo = message.photo[-1]  # последний размер — самый крупный
    if photo.file_size and photo.file_size > MAX_IMAGE_BYTES:
        await message.answer("Фото слишком большое. Пришли его как фото (не файлом).")
        return

    status = await message.answer("🔍 Распознаю блюдо…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        buffer = await message.bot.download(photo.file_id)
        if buffer is None:
            raise FoodRecognitionError("Не удалось скачать фото из Telegram")
        analysis = await analyze_photo(buffer.read())
    except FoodRecognitionError as e:  # включая «нет ключа» и «не видно еды»
        await status.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка распознавания фото еды")
        await status.edit_text(GENERIC_ERROR)
        return

    await status.delete()
    await _show_card(message, state, analysis, photo_file_id=photo.file_id)


@router.message(StateFilter(None, FoodStates), F.voice)
async def handle_food_voice(message: Message, state: FSMContext) -> None:
    """Голосовое сообщение: расшифровываем и считаем КБЖУ по тексту."""
    if await _ensure_onboarded(message) is None:
        return

    status = await message.answer("🎤 Слушаю…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        buffer = await message.bot.download(message.voice.file_id)
        if buffer is None:
            raise TranscriptionError("Не удалось скачать голосовое из Telegram")
        spoken = await transcribe(buffer.read())
    except (VoiceNotConfigured, TranscriptionError) as e:
        await status.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка расшифровки голосового сообщения")
        await status.edit_text("Не получилось разобрать голосовое. Попробуй ещё раз или напиши текстом.")
        return

    await status.edit_text(f"🎤 Услышал: {spoken}\n\n🔍 Считаю КБЖУ…")

    try:
        analysis = await analyze_text(spoken)
    except FoodRecognitionError as e:  # включая «нет ключа» и «не видно еды»
        await status.edit_text(f"🎤 Услышал: {spoken}\n\n{e}")
        return
    except Exception:
        logger.exception("Ошибка расчёта КБЖУ по голосовому сообщению")
        await status.edit_text(GENERIC_ERROR)
        return

    await status.delete()
    await _show_card(message, state, analysis, photo_file_id=None)


@router.message(FoodStates.waiting_input, F.text)
async def handle_food_text(message: Message, state: FSMContext) -> None:
    status = await message.answer("🔍 Считаю КБЖУ…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        analysis = await analyze_text(message.text)
    except FoodRecognitionError as e:  # включая «нет ключа» и «не видно еды»
        await status.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка распознавания еды по тексту")
        await status.edit_text(GENERIC_ERROR)
        return

    await status.delete()
    await _show_card(message, state, analysis, photo_file_id=None)


async def _load_analysis(state: FSMContext) -> FoodAnalysis | None:
    data = await state.get_data()
    raw = data.get("analysis")
    return FoodAnalysis.from_dict(raw) if raw else None


def _rescaled(analysis: FoodAnalysis, new_weight_g: float) -> FoodAnalysis:
    scaled = scale_nutrition(
        {
            "calories": analysis.calories,
            "protein_g": analysis.protein_g,
            "fat_g": analysis.fat_g,
            "carbs_g": analysis.carbs_g,
            "fiber_g": analysis.fiber_g,
        },
        from_weight_g=analysis.weight_g,
        to_weight_g=new_weight_g,
    )
    return FoodAnalysis(
        name=analysis.name,
        weight_g=new_weight_g,
        calories=scaled["calories"],
        protein_g=scaled["protein_g"],
        fat_g=scaled["fat_g"],
        carbs_g=scaled["carbs_g"],
        fiber_g=scaled["fiber_g"],
        confidence=analysis.confidence,
        comment=analysis.comment,
    )


@router.callback_query(FoodStates.confirming, F.data.in_({CB_LESS, CB_MORE}))
async def change_portion(callback: CallbackQuery, state: FSMContext) -> None:
    analysis = await _load_analysis(state)
    if analysis is None:
        await callback.answer("Карточка устарела, пришли фото заново", show_alert=True)
        return

    new_weight = adjust_weight(analysis.weight_g, bigger=callback.data == CB_MORE)
    if new_weight == analysis.weight_g:
        await callback.answer("Дальше менять некуда")
        return

    await _update_card(callback.message, state, _rescaled(analysis, new_weight))
    await callback.answer()


@router.callback_query(FoodStates.confirming, F.data == CB_WEIGHT)
async def ask_weight(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FoodStates.correcting_weight)
    await callback.message.answer("Сколько граммов в порции? Например: 320")
    await callback.answer()


@router.message(FoodStates.correcting_weight, F.text)
async def apply_weight(message: Message, state: FSMContext) -> None:
    weight = parse_float(message.text)
    if weight is None or not (MIN_WEIGHT_G <= weight <= MAX_WEIGHT_G):
        await message.answer(
            f"Введи вес числом от {MIN_WEIGHT_G:.0f} до {MAX_WEIGHT_G:.0f} г, например: 320"
        )
        return

    analysis = await _load_analysis(state)
    if analysis is None:
        await state.clear()
        await message.answer("Карточка устарела — пришли фото заново.")
        return

    await state.set_state(FoodStates.confirming)
    await _update_card(message, state, _rescaled(analysis, weight))


@router.callback_query(FoodStates.confirming, F.data == CB_WRONG_DISH)
async def ask_correct_dish(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FoodStates.correcting_dish)
    await callback.message.answer("Что это за блюдо? Напиши название — пересчитаю.")
    await callback.answer()


@router.message(FoodStates.correcting_dish, F.text)
async def apply_correct_dish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    hint = message.text.strip()

    status = await message.answer("🔍 Пересчитываю…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        if photo_file_id:
            # Фото анализируем заново с подсказкой пользователя: название берём
            # из подсказки, а вес порции модель по-прежнему оценивает по фото.
            buffer = await message.bot.download(photo_file_id)
            if buffer is None:
                raise FoodRecognitionError("Не удалось скачать фото из Telegram")
            analysis = await analyze_photo(buffer.read(), hint=hint)
        else:
            analysis = await analyze_text(hint)
    except FoodRecognitionError as e:  # включая «нет ключа» и «не видно еды»
        await status.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка пересчёта блюда по уточнению пользователя")
        await status.edit_text(GENERIC_ERROR)
        return

    await status.delete()
    await state.set_state(FoodStates.confirming)
    await _update_card(message, state, analysis)


@router.callback_query(FoodStates.confirming, F.data == CB_SAVE)
async def save_food(callback: CallbackQuery, state: FSMContext) -> None:
    analysis = await _load_analysis(state)
    if analysis is None:
        await callback.answer("Карточка устарела, пришли фото заново", show_alert=True)
        return

    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    meal_type = guess_meal_type(datetime.now(get_zone(DEFAULT_TIMEZONE)))

    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None or not user.onboarding_completed:
            await callback.answer("Сначала настрой профиль: /start", show_alert=True)
            return

        await save_meal(
            session,
            user_id=user.id,
            analysis=analysis,
            source=MealSourceEnum.PHOTO if photo_file_id else MealSourceEnum.TEXT,
            meal_type=meal_type,
            photo_file_id=photo_file_id,
        )
        totals = await get_today_totals(session, user.id, timezone_name=user.timezone)
        norms = (
            user.daily_calories,
            user.daily_protein_g,
            user.daily_fat_g,
            user.daily_carbs_g,
            user.daily_fiber_g,
        )
        # Игровой итог считаем здесь же: запись еды может закрыть задание дня,
        # и узнать об этом приятнее сразу, а не при следующем входе в приложение.
        game = await sync_today(
            session,
            user,
            meals_count=len(await list_today_meals(session, user.id, timezone_name=user.timezone)),
            calories=totals.calories,
            fiber_g=totals.fiber_g,
            water_ml=await today_total_ml(session, user.id, timezone_name=user.timezone),
            timezone_name=user.timezone,
        )

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        _render_day_summary(analysis, MEAL_TYPE_RU[meal_type], totals, norms, game),
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer("Сохранено ✅")


def _render_game_lines(game: dict) -> list[str]:
    """Уровень, стрик и только что закрытые задания — короткой припиской."""
    if not game:
        return []

    lines = [""]
    for code in game.get("just_completed", []):
        quest = next((q for q in game["quests"] if q["code"] == code), None)
        if quest:
            lines.append(f"✅ Задание закрыто: {quest['title']} +{quest['xp']} 💎")

    for award in game.get("new_awards", []):
        lines.append(f"{award['icon']} Новая награда: {award['title']}")

    progress = f"💎 Уровень {game['level']} · {game['xp_in_level']}/{game['xp_to_next']}"
    if game.get("streak"):
        progress += f" · 🔥 {game['streak']} дней подряд"
    lines.append(progress)
    return lines


def _render_day_summary(analysis, meal_type_label, totals, norms, game=None) -> str:
    calories_norm, protein_norm, fat_norm, carbs_norm, fiber_norm = norms
    lines = [f"✅ Записал: {analysis.name} ({meal_type_label})", ""]

    if calories_norm:
        lines += [
            f"🔥 {_num(totals.calories)} / {calories_norm} ккал",
            f"{render_progress_bar(totals.calories, calories_norm)} · "
            f"{format_remaining(totals.calories, calories_norm)} ккал",
            "",
        ]
    lines += [
        f"🥩 Б {_num(totals.protein_g)} / {protein_norm or '—'} г",
        f"🥑 Ж {_num(totals.fat_g)} / {fat_norm or '—'} г",
        f"🍚 У {_num(totals.carbs_g)} / {carbs_norm or '—'} г",
        f"🥦 Клетчатка {_num(totals.fiber_g)} / {fiber_norm or '—'} г",
    ]
    lines += _render_game_lines(game)
    return "\n".join(lines)


@router.callback_query(FoodStates.confirming, F.data == CB_CANCEL)
async def cancel_food(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Не записал ❌")
    await callback.answer()
