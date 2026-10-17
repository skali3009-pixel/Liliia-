"""Clickable tariff descriptions; no invoices or access changes."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.main_menu import MENU_TARIFFS
from services.tariffs import PLANS, find_plan, overview_text, plan_text
from services import platega

router = Router(name="tariffs")


def tariff_keyboard(user_id=None):
    builder = InlineKeyboardBuilder()
    for plan in PLANS:
        builder.button(text=f"{plan.days} дней · {plan.price_rub:,} ₽".replace(",", " "),
                       callback_data=f"tariff:{plan.id}")
    if platega.enabled(user_id):
        builder.button(text="Оплатить 490 ₽ · 30 дней", callback_data="platega:buy")
    builder.adjust(1)
    return builder.as_markup()


async def send_tariffs(message: Message):
    await message.answer(overview_text(), reply_markup=tariff_keyboard(getattr(getattr(message, "from_user", None), "id", None)))


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
    await callback.message.answer(plan_text(plan), reply_markup=tariff_keyboard(getattr(getattr(callback, "from_user", None), "id", None)))


@router.callback_query(F.data == "platega:buy")
async def buy_platega(callback: CallbackQuery):
    await callback.answer()
    try:
        order = await platega.create_order(callback.from_user.id)
    except platega.PaymentError as error:
        await callback.message.answer(str(error))
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить 490 ₽", url=order.url)
    builder.button(text="Проверить оплату", callback_data=f"platega:check:{order.id}")
    builder.adjust(1)
    await callback.message.answer(
        "AURA на 30 дней — 490 ₽. Автосписаний нет.\n"
        "После подтверждения платежа доступ продлится автоматически, бот пришлёт сообщение. "
        "Если сообщение задержалось, нажми «Проверить оплату». Оставшиеся дни сохранятся.\n"
        "Комиссия способа оплаты, если есть, показана на странице Platega до оплаты.\n"
        "Условия покупки и возврата: /legal. Помощь: /problem.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("platega:check:"))
async def check_platega(callback: CallbackQuery):
    await callback.answer()
    try:
        status = await platega.check_order(callback.data.rsplit(":", 1)[-1], callback.from_user.id, source="bot_check", bot=callback.bot)
        view = await platega.subscription_view(callback.from_user.id)
        text = {"CONFIRMED": "Оплата подтверждена. " + view["subscription_text"],
                "PENDING": "Оплата ещё не подтверждена. Проверь через минуту; повторно платить не нужно.",
                "CANCELED": "Счёт отменён. Новый можно открыть через /tariffs.",
                "CHARGEBACKED": "По платежу оформлен возврат. Помощь: /problem."}[status]
    except platega.PaymentError as error:
        text = str(error)
    await callback.message.answer(text)


@router.callback_query(F.data == "platega:subscription")
async def subscription_status(callback: CallbackQuery):
    await callback.answer()
    await send_subscription(callback.message, callback.from_user.id)


async def send_subscription(message, user_id):
    view = await platega.subscription_view(user_id)
    builder = InlineKeyboardBuilder()
    if view["checkout_enabled"]:
        builder.button(text="Продлить на 30 дней · 490 ₽", callback_data="platega:buy")
    await message.answer(view["subscription_text"] + "\n" + view["checkout_note"],
                         reply_markup=builder.as_markup() if view["checkout_enabled"] else None)
