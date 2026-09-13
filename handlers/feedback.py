"""«Что-то не так»: рассказать о проблеме и получить ответ.

Падения бот теперь ловит сам. Но самое частое — не падение: «пришёл какой-то
отчёт, что это?», «непонятно, куда нажимать». В логах такое выглядит
безупречно, и узнать о нём можно только от человека.

Ответ владельца идёт тем же путём обратно. Без этого получился бы ящик для
жалоб: у многих в Telegram нет имени пользователя, и написать им в ответ
владелец не смог бы никак, даже зная номер.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from keyboards.main_menu import MENU_TEXTS, main_menu_keyboard
from keyboards.profile import CB_PROBLEM
from services import feedback
from states.feedback import FeedbackStates

logger = logging.getLogger(__name__)
router = Router(name="feedback")

CB_TELL = "fb_tell"
CB_ANSWER = "fb_answer:"

ASK = (
    "✍️ Расскажи, что случилось.\n\n"
    "Своими словами: что нажала, что ожидала увидеть и что увидела вместо "
    "этого. Даже одна фраза помогает — «непонятно, куда нажимать» это тоже "
    "ответ.\n\n"
    "Напиши сообщением. Передумала — нажми любую кнопку меню."
)

THANKS = (
    "Спасибо, передала. 🐆\n\n"
    "Если понадобится уточнить, тебе ответят прямо сюда, в этот чат."
)

TOO_OFTEN = (
    "Я уже передала твои сообщения — давай подождём ответа, чтобы не "
    "потерялось важное. Напиши ещё раз попозже."
)

NOWHERE = (
    "Сейчас передать некому — бот ещё настраивается. Попробуй чуть позже."
)


def answer_button(user_id: int):
    """Кнопка «Ответить» под сообщением владельцу.

    Без неё владелец читает жалобу и не может ничего: у человека может не
    быть имени пользователя, и найти его в Telegram по номеру нельзя.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✉️ Ответить", callback_data=f"{CB_ANSWER}{user_id}")
    return builder.as_markup()


# Кнопка меню важнее недописанного рассказа: иначе человек, ушедший из него
# в «Воду», останется в состоянии письма и его следующая фраза уедет владельцу.
@router.message(StateFilter(FeedbackStates), F.text.in_(MENU_TEXTS))
async def leave_writing(message: Message, state: FSMContext) -> None:
    await state.clear()
    raise SkipHandler


@router.message(Command("problem"))
async def start_by_command(message: Message, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.writing)
    await message.answer(ASK)


@router.callback_query(F.data.in_({CB_TELL, CB_PROBLEM}))
async def start_by_button(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.writing)
    await callback.message.answer(ASK)
    await callback.answer()


@router.message(FeedbackStates.writing, F.text)
async def take_report(message: Message, state: FSMContext, bot: Bot) -> None:
    text = feedback.clean(message.text)
    if not text:
        await message.answer("Пустое сообщение передавать нечего — напиши словами.")
        return

    await state.clear()
    if not config.ADMIN_IDS:
        await message.answer(NOWHERE, reply_markup=main_menu_keyboard())
        return
    if not feedback.allowed(message.from_user.id):
        await message.answer(TOO_OFTEN, reply_markup=main_menu_keyboard())
        return

    report = feedback.Report(
        user_id=message.from_user.id,
        name=(message.from_user.full_name or "").strip(),
        where="чат",
        text=text,
    )
    delivered = await feedback.deliver(bot, report,
                                       keyboard=answer_button(report.user_id))
    await message.answer(THANKS if delivered else NOWHERE,
                         reply_markup=main_menu_keyboard())


# --- Ответ владельца -------------------------------------------------------

@router.callback_query(F.data.startswith(CB_ANSWER))
async def start_answer(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Это не твоя кнопка", show_alert=True)
        return

    try:
        user_id = int(callback.data.removeprefix(CB_ANSWER))
    except ValueError:
        await callback.answer("Не понимаю, кому отвечать", show_alert=True)
        return

    await state.set_state(FeedbackStates.answering)
    await state.update_data(answer_to=user_id)
    await callback.message.answer(
        f"Напиши ответ для {user_id} — я передам его в чат этому человеку.\n\n"
        "Передумала — нажми любую кнопку меню."
    )
    await callback.answer()


@router.message(FeedbackStates.answering, F.text)
async def send_answer(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    user_id = data.get("answer_to")
    await state.clear()

    if not isinstance(user_id, int):
        await message.answer("Потеряла, кому отвечать. Нажми «Ответить» ещё раз.")
        return

    if await feedback.answer(bot, user_id, message.text):
        await message.answer("Отправила ✅", reply_markup=main_menu_keyboard())
    else:
        await message.answer(
            "Не получилось доставить — человек мог заблокировать бота.",
            reply_markup=main_menu_keyboard(),
        )
