"""Clickable tariff descriptions; no invoices or access changes."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.main_menu import MENU_TARIFFS
from services.tariffs import PLANS, find_plan, overview_text, plan_text

router = Router(name="tariffs")


def tariff_keyboard():
    builder = InlineKeyboardBuilder()
    for plan in PLANS:
        builder.button(text=f"{plan.days} дней · {plan.price_rub:,} ₽".replace(",", " "),
                       callback_data=f"tariff:{plan.id}")
    builder.adjust(1)
    return builder.as_markup()


async def send_tariffs(message: Message):
    await message.answer(overview_text(), reply_markup=tariff_keyboard())


@router.message(Command("tariffs"))
@router.message(F.text == MENU_TARIFFS)
async def show_tariffs(message: Message, state: FSMContext):
    # Browsing prices must not erase an unfinished questionnaire. Other input
    # flows end so that the next ordinary message isn't mistaken for an answer.
    current = await state.get_state()
    if current and not current.startswith("OnboardingStates:"):
        await state.clear()
    await send_tariffs(message)


@router.callback_query(F.data.startswith("tariff:"))
async def show_plan(callback: CallbackQuery):
    plan = find_plan((callback.data or "").split(":", 1)[-1])
    if plan is None:
        await callback.answer("Тариф не найден. Открой /tariffs заново.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(plan_text(plan), reply_markup=tariff_keyboard())
