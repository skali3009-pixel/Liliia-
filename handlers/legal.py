"""Согласие с документами при первом запуске и управление данными.

Человек видит, чей это бот, что он умеет и под какими условиями работает, —
и только после явного нажатия «Принимаю» попадает в анкету. Согласие на
рекламу спрашивается отдельно: по закону оно добровольное и на доступ к
сервису влиять не может.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import get_session
from models import User
from services import deletion
from services.legal import LEGAL_VERSION, document_url, links_ready
from services.slides import send_slide
from services.video_notes import send_circle

logger = logging.getLogger(__name__)
router = Router(name="legal")

CB_ACCEPT = "legal:accept"
CB_ADS_ON = "legal:ads_on"
CB_ADS_OFF = "legal:ads_off"


def _owner_line() -> str:
    return config.LEGAL_OWNER or "владелец бота"


def welcome_text() -> str:
    """Первый экран: что это, чьё это и на что человек соглашается.

    Список умений переписан по тому, что в боте есть на самом деле.
    Прежний молчал о половине: ни заготовок, ни рецептов, ни «сфоткай
    полку», ни того, что всё главное работает прямо в чате, без
    приложения. Человек соглашается на обработку данных о здоровье — и
    должен знать, ради чего.

    Юридическая часть ниже не тронута: её формулировки Лилия решила
    оставить как есть.
    """
    return (
        "👋 AURA — питание, движение и тело в одном месте.\n\n"
        "Что умеет:\n"
        "• еда по фото, голосом или текстом — КБЖУ считает сама;\n"
        "• отвечает «что съесть»: рецепты на 15 минут, меню нутрициолога, "
        "заготовки впрок — и «Реши за меня», если выбирать нет сил;\n"
        "• помогает в магазине: сфотографируй полку — скажет, что взять;\n"
        "• 17 программ и 103 упражнения (тело, лицо, глаза, осанка, "
        "женское) — каждое движение показано, без ухода в чужие видео;\n"
        "• считает воду, шаги с телефона, самочувствие и задания дня;\n"
        "• ведёт вес, объёмы, фото по неделям и женский календарь;\n"
        "• всё главное работает и в чате, без приложения — команды под "
        "синей кнопкой рядом с полем ввода.\n\n"
        f"Владелец: {_owner_line()}\n\n"
        "⚠️ Это не медицинская услуга. Расчёты и рекомендации справочные, "
        "они не заменяют консультацию врача.\n\n"
        "Нажимая «Принимаю», ты подтверждаешь, что тебе есть 18 лет, "
        "ознакомлена с документами ниже и даёшь согласие на обработку своих "
        "данных, включая сведения о здоровье."
    )


def consent_keyboard() -> InlineKeyboardMarkup:
    """Документы — ссылками, согласие — кнопкой."""
    builder = InlineKeyboardBuilder()
    if links_ready():
        builder.button(text="📄 Оферта", url=document_url("offer"))
        builder.button(text="🔒 Политика данных", url=document_url("privacy"))
        builder.button(text="✍️ Согласие на обработку", url=document_url("consent"))
        builder.adjust(2, 1)
    builder.row()
    builder.button(text="✅ Принимаю", callback_data=CB_ACCEPT)
    return builder.as_markup()


def ads_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, присылайте", callback_data=CB_ADS_ON)
    builder.button(text="Нет, спасибо", callback_data=CB_ADS_OFF)
    return builder.as_markup()


async def needs_consent(user: User | None) -> bool:
    """Нужно ли просить согласие: его нет или изменились документы."""
    return user is None or user.legal_version != LEGAL_VERSION


@router.callback_query(F.data == CB_ACCEPT)
async def accept(callback: CallbackQuery) -> None:
    """Записываем согласие и спрашиваем про рекламу — отдельно."""
    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None:
            user = User(id=callback.from_user.id)
            session.add(user)
        user.legal_version = LEGAL_VERSION
        user.legal_accepted_at = datetime.now(timezone.utc)
        await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Спасибо. Отдельный вопрос: присылать иногда новости о боте?\n\n"
        "Это не влияет на работу бота — напоминания о твоих добавках и делах "
        "дня приходят в любом случае. Отказаться можно потом командой "
        "/stop_ads.",
        reply_markup=ads_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.in_({CB_ADS_ON, CB_ADS_OFF}))
async def set_ads(callback: CallbackQuery, state: FSMContext) -> None:
    wants = callback.data == CB_ADS_ON

    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is not None:
            user.marketing_consent = wants
            await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Хорошо, буду присылать изредка." if wants else "Хорошо, рекламы не будет."
    )
    await callback.answer()

    # Знакомство: Ая здоровается голосом до первого вопроса. Момент
    # наступает ровно один раз — согласие спрашивают, пока его нет.
    await send_circle(callback.message, "hello")
    # И картинкой — ради чего человек сейчас будет отвечать на девять
    # вопросов. Словами это здесь уже сказано, и второй раз не читают.
    await send_slide(callback.message, "what_is_inside")

    # Дальше — обычный путь: анкета или главное меню.
    from handlers.onboarding import begin_onboarding

    await begin_onboarding(callback.message, state, callback.from_user.id)


@router.message(Command("stop_ads"))
async def stop_ads(message: Message) -> None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is not None:
            user.marketing_consent = False
            await session.commit()
    await message.answer("Готово, рекламных сообщений больше не будет.")


CB_DELETE_YES = "legal:delete_yes"
CB_DELETE_NO = "legal:delete_no"


@router.message(Command("delete"))
async def ask_delete(message: Message) -> None:
    """Отзыв согласия и удаление данных — обещаны в политике, значит работают."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить всё", callback_data=CB_DELETE_YES)
    builder.button(text="Отмена", callback_data=CB_DELETE_NO)

    await message.answer(
        "Удалить все твои данные?\n\n"
        "Профиль, дневник питания, воду, тренировки, замеры, фотографии и "
        "самочувствие — безвозвратно. Подписка при этом не возвращается "
        "автоматически: если нужен возврат, напиши "
        f"{config.LEGAL_EMAIL or 'владельцу'}.\n\n"
        "Это действие нельзя отменить.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == CB_DELETE_NO)
async def cancel_delete(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Хорошо, ничего не удаляю.")
    await callback.answer()


@router.callback_query(F.data == CB_DELETE_YES)
async def do_delete(callback: CallbackQuery) -> None:
    async with get_session() as session:
        # Почти всё уходит каскадом, но не всё: обратная дружба и команда
        # каскадом не описываются и пережили бы удаление.
        await deletion.purge(session, callback.from_user.id)

    await callback.message.edit_text(
        "Готово. Все данные удалены, согласие отозвано.\n\n"
        "Если захочешь вернуться — просто напиши /start, начнём с чистого листа."
    )
    await callback.answer()


@router.message(Command("legal"))
async def show_documents(message: Message) -> None:
    """Документы всегда под рукой, а не только при первом запуске."""
    if not links_ready():
        await message.answer("Ссылки на документы появятся, когда будет настроен адрес сайта.")
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Оферта", url=document_url("offer"))
    builder.button(text="🔒 Политика данных", url=document_url("privacy"))
    builder.button(text="✍️ Согласие на обработку", url=document_url("consent"))
    builder.button(text="📣 Согласие на рассылку", url=document_url("marketing"))
    builder.adjust(2, 2)

    await message.answer(
        f"Документы сервиса. Владелец: {_owner_line()}.\n"
        f"Действующая редакция: {LEGAL_VERSION}.",
        reply_markup=builder.as_markup(),
    )
