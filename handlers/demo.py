"""Бесплатная примерка еды: один настоящий разбор до оплаты.

Человек уже получил норму, но ещё не видел главную функцию в работе. Здесь
он один раз присылает фото, голосовое или текст и получает реальные калории
и БЖУ. Это не пробный доступ: меню, дневник и тренировки по-прежнему
закрыты, а успешный разбор расходуется один раз и навсегда.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import update

import config
from db import get_session
from handlers.access import buy_keyboard, paywall_text
from handlers.food import GENERIC_ERROR, MAX_IMAGE_BYTES, PHOTO_TIPS
from keyboards.main_menu import MENU_TEXTS
from models import User
from services import analytics, demo as demo_service, usage
from services.food_vision import (
    FoodAnalysis,
    FoodNotRecognized,
    FoodRecognitionError,
    analyze_photo,
    analyze_text,
)
from services.subscriptions import check_access
from services.transcription import TranscriptionError, VoiceNotConfigured, transcribe
from states.demo import DemoStates

logger = logging.getLogger(__name__)
router = Router(name="demo")

PROMPT = (
    "🐆 Примерка: один разбор еды — бесплатно.\n\n"
    "Пришли фото тарелки, голосовое или опиши словами, что съел. "
    "Посчитаю калории, БЖУ и покажу, сколько это от твоей нормы.\n\n"
    "Это один раз и без оплаты. Потом можно спокойно решить, нужен ли доступ."
)

CANCEL_TEXT = "Хорошо. Если захочешь — нажми «Попробовать на еде» ещё раз."


def _num(value: float) -> str:
    text = f"{float(value):.1f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _start_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="demo:cancel")
    return builder.as_markup()


def offer_keyboard() -> InlineKeyboardMarkup:
    """Кнопки под результатом примерки: цена и план."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Открыть доступ · 290 ₽", callback_data="platega:promo290")
    builder.button(text="Показать план", callback_data="onb:show_plan")
    builder.adjust(1)
    return builder.as_markup()


def _result_text(analysis: FoodAnalysis, user: User | None) -> str:
    lines = [
        "✅ Вот как это работает.",
        "",
        f"🍽 {analysis.name}",
        f"⚖️ ~{_num(analysis.weight_g)} г",
        "",
        f"🔥 ≈ {_num(analysis.calories)} ккал",
        f"🥩 Б {_num(analysis.protein_g)} · 🥑 Ж {_num(analysis.fat_g)} · "
        f"🍚 У {_num(analysis.carbs_g)} г",
    ]
    if analysis.fiber_g:
        lines.append(f"🥦 Клетчатка {_num(analysis.fiber_g)} г")
    if analysis.comment:
        lines += ["", f"💬 {analysis.comment}"]

    norm = user.daily_calories if user else None
    if norm:
        share = round(analysis.calories / norm * 100)
        lines += ["", f"Это {share}% твоей нормы — {norm} ккал в день."]

    lines += [
        "",
        "С доступом такой разбор сразу уходит в дневник: видно остаток нормы, "
        "можно поправить порцию и подобрать блюдо. Плюс тренировки, вода, шаги "
        "и графики.",
        "",
        "Первый месяц — 290 ₽ вместо 490 ₽. Без автосписаний.",
    ]
    return "\n".join(lines)


@router.callback_query(F.data == "demo:food")
async def start_demo(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать инструкцию, если примерка ещё доступна."""
    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        access = await check_access(session, callback.from_user.id)
        available = demo_service.available(user, allowed=access.allowed)
        if available:
            await analytics.note(session, callback.from_user.id,
                                 analytics.DEMO_STARTED, once="once_ever")
            await session.commit()

    if access.allowed:
        await callback.answer("Доступ уже открыт — примерка не нужна.",
                              show_alert=True)
        return
    if not available:
        await callback.answer()
        await callback.message.answer(paywall_text(access), reply_markup=buy_keyboard())
        return

    await callback.answer()
    await state.set_state(DemoStates.waiting_food)
    await callback.message.answer(PROMPT, reply_markup=_start_keyboard())


@router.callback_query(F.data == "demo:cancel")
async def cancel_demo(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(CANCEL_TEXT)


async def _ensure_available(message: Message, state: FSMContext) -> bool:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        access = await check_access(session, message.from_user.id)
        available = demo_service.available(user, allowed=access.allowed)
    if available:
        return True
    await state.clear()
    await message.answer(paywall_text(access), reply_markup=buy_keyboard())
    return False


async def _record_spend(user_id: int, kind: str, spent: list) -> None:
    if not spent:
        return
    try:
        async with get_session() as session:
            for item in spent:
                await usage.record(session, user_id=user_id, kind=kind,
                                   model=config.VISION_MODEL, usage=item)
    except Exception:  # noqa: BLE001
        logger.exception("Не записался расход на примерку еды")


async def _consume(user_id: int) -> tuple[User | None, bool]:
    """Списать примерку и вернуть пользователя для текста результата."""
    async with get_session() as session:
        user = await session.get(User, user_id)
        result = await session.execute(
            update(User)
            .where(User.id == user_id, User.demo_food_at.is_(None))
            .values(demo_food_at=datetime.now(timezone.utc))
        )
        used = result.rowcount == 1
        if used:
            await analytics.note(session, user_id, analytics.DEMO_DONE,
                                 once="once_ever")
        await session.commit()
        return user, used


async def _finish(status: Message, user_id: int, state: FSMContext,
                  analysis: FoodAnalysis, spent: list, kind: str) -> None:
    await _record_spend(user_id, kind, spent)
    try:
        user, used = await _consume(user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось отметить примерку еды")
        # Разбор уже случился — не наказываем человека за сбой базы.
        async with get_session() as session:
            user = await session.get(User, user_id)
        used = True

    if not used:
        await state.clear()
        await status.edit_text(
            "Похоже, примерка уже была использована. Открой доступ — внутри "
            "дневник, остаток нормы и все остальные возможности.",
            reply_markup=offer_keyboard(),
        )
        return

    await state.clear()
    await status.edit_text(_result_text(analysis, user),
                           reply_markup=offer_keyboard())


@router.message(DemoStates.waiting_food, F.photo)
async def demo_photo(message: Message, state: FSMContext) -> None:
    if not await _ensure_available(message, state):
        return

    photo = message.photo[-1]
    if photo.file_size and photo.file_size > MAX_IMAGE_BYTES:
        await message.answer("Фото слишком большое. Пришли его как фото (не файлом).")
        return

    status = await message.answer("🔍 Распознаю блюдо…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    spent: list = []
    try:
        buffer = await message.bot.download(photo.file_id)
        if buffer is None:
            raise FoodRecognitionError("Не удалось скачать фото из Telegram")
        analysis = await analyze_photo(buffer.read(), on_usage=spent.append)
    except FoodNotRecognized as error:
        await status.edit_text(f"{error}{PHOTO_TIPS}")
        return
    except FoodRecognitionError as error:
        await status.edit_text(str(error))
        return
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка распознавания фото в примерке")
        await status.edit_text(GENERIC_ERROR)
        return

    await _finish(status, message.from_user.id, state, analysis, spent, "photo")


@router.message(DemoStates.waiting_food, F.voice)
async def demo_voice(message: Message, state: FSMContext) -> None:
    if not await _ensure_available(message, state):
        return

    status = await message.answer("🎤 Слушаю…")
    await message.bot.send_chat_action(message.chat.id, "typing")
    spent: list = []
    try:
        buffer = await message.bot.download(message.voice.file_id)
        if buffer is None:
            raise TranscriptionError("Не удалось скачать голосовое из Telegram")
        spoken = await transcribe(buffer.read())
    except (VoiceNotConfigured, TranscriptionError) as error:
        await status.edit_text(str(error))
        return
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка расшифровки голосового в примерке")
        await status.edit_text("Не получилось разобрать голосовое. "
                               "Попробуй ещё раз или напиши текстом.")
        return

    await status.edit_text(f"🎤 Услышал: {spoken}\n\n🔍 Считаю…")
    try:
        analysis = await analyze_text(spoken, on_usage=spent.append)
    except FoodNotRecognized as error:
        await status.edit_text(f"🎤 Услышал: {spoken}\n\n{error}")
        return
    except FoodRecognitionError as error:
        await status.edit_text(f"🎤 Услышал: {spoken}\n\n{error}")
        return
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка разбора голосового в примерке")
        await status.edit_text("Не получилось посчитать. Попробуй ещё раз "
                               "или напиши текстом.")
        return

    await _finish(status, message.from_user.id, state, analysis, spent, "voice")


@router.message(DemoStates.waiting_food, F.text, ~F.text.in_(MENU_TEXTS),
                ~F.text.startswith("/"))
async def demo_text(message: Message, state: FSMContext) -> None:
    if not await _ensure_available(message, state):
        return

    text = (message.text or "").strip()
    if len(text) < 2:
        await message.answer("Опиши еду словами — например: «тарелка борща и два куска хлеба».")
        return

    status = await message.answer("🔍 Считаю…")
    spent: list = []
    try:
        analysis = await analyze_text(text, on_usage=spent.append)
    except FoodNotRecognized as error:
        await status.edit_text(f"{error}{PHOTO_TIPS}")
        return
    except FoodRecognitionError as error:
        await status.edit_text(str(error))
        return
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка разбора текста в примерке")
        await status.edit_text(GENERIC_ERROR)
        return

    await _finish(status, message.from_user.id, state, analysis, spent, "text")


@router.message(DemoStates.waiting_food)
async def demo_other(message: Message) -> None:
    await message.answer(
        "Пришли фото тарелки, голосовое или опиши еду словами. "
        "Или нажми «Отмена» под инструкцией."
    )
