"""Платный доступ: экран подписки, оплата звёздами и продление.

Оплата идёт звёздами Telegram: они не требуют ни юрлица, ни договора с
банком, и Telegram сам списывает следующий месяц, пока человек не отменит
подписку. Отмена — тоже на его стороне, в настройках Telegram.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import get_session
from models import SubscriptionSource
from services.subscriptions import Access, activate, check_access, stats

logger = logging.getLogger(__name__)
router = Router(name="access")

CB_BUY = "sub:buy"
PAYLOAD_PREFIX = "sub_month"

# Период списания задаётся в секундах и у Telegram может быть только месячным.
MONTH_SECONDS = 30 * 24 * 60 * 60


def paywall_text(access: Access) -> str:
    """Что показать человеку без доступа."""
    if access.status.value == "trial":
        return (
            "🔒 Пробный период закончился\n\n"
            "Дневник, распознавание еды по фото и голосу, тренировки, замеры и "
            "прогресс — всё остаётся на месте и включится сразу после оплаты.\n\n"
            f"Подписка — {config.SUB_PRICE_STARS} ⭐ в месяц, "
            "списывается автоматически. Отменить можно в любой момент в настройках Telegram."
        )
    return (
        "🔒 Доступ закрыт\n\n"
        "Твои записи никуда не делись — они ждут тебя.\n\n"
        f"Подписка — {config.SUB_PRICE_STARS} ⭐ в месяц. "
        "Списывается автоматически, отменить можно в любой момент."
    )


def buy_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⭐ Оформить за {config.SUB_PRICE_STARS} в месяц", callback_data=CB_BUY)
    return builder.as_markup()


async def send_paywall(message: Message, access: Access) -> None:
    await message.answer(paywall_text(access), reply_markup=buy_keyboard())


@router.message(Command("subscription"))
async def show_subscription(message: Message) -> None:
    """Состояние подписки: сколько осталось и как продлить."""
    async with get_session() as session:
        access = await check_access(session, message.from_user.id)

    if access.is_admin:
        await message.answer("Ты владелец — доступ всегда открыт.")
        return

    if not access.allowed:
        await send_paywall(message, access)
        return

    left = access.days_left
    tail = "день" if left % 10 == 1 and left % 100 != 11 else (
        "дня" if left % 10 in (2, 3, 4) and left % 100 not in (12, 13, 14) else "дней"
    )
    kind = "Пробный период" if access.is_trial else "Подписка"
    renew = (
        "Продлевается автоматически."
        if access.is_recurring
        else "Автопродления нет — оформи, чтобы не прерывалось."
    )

    await message.answer(
        f"{kind}: осталось {left} {tail}.\n{renew}",
        reply_markup=None if access.is_recurring else buy_keyboard(),
    )


@router.callback_query(F.data == CB_BUY)
async def start_payment(callback: CallbackQuery) -> None:
    """Счёт на подписку. Звёзды не требуют платёжного провайдера."""
    try:
        link = await callback.bot.create_invoice_link(
            title="Доступ к приложению",
            description=(
                "Дневник питания, распознавание еды по фото и голосу, тренировки, "
                "замеры и прогресс. Списывается раз в месяц, отменить можно в любой момент."
            ),
            payload=f"{PAYLOAD_PREFIX}:{callback.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label="Месяц доступа", amount=config.SUB_PRICE_STARS)],
            subscription_period=MONTH_SECONDS,
        )
    except Exception:
        logger.exception("Не удалось создать счёт")
        await callback.answer("Не получилось открыть оплату, попробуй ещё раз", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text=f"⭐ Оплатить {config.SUB_PRICE_STARS}", url=link)
    await callback.message.answer(
        "Счёт готов. После оплаты доступ откроется сразу.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.pre_checkout_query()
async def approve_payment(query: PreCheckoutQuery) -> None:
    """Telegram спрашивает подтверждение перед списанием."""
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def payment_received(message: Message) -> None:
    """Оплата прошла — открываем доступ. Сюда же приходят автопродления."""
    payment = message.successful_payment

    async with get_session() as session:
        await activate(
            session,
            message.from_user.id,
            days=config.SUB_PERIOD_DAYS,
            source=SubscriptionSource.STARS,
            amount=payment.total_amount,
            charge_id=payment.telegram_payment_charge_id or "",
            is_recurring=bool(payment.is_recurring),
        )

    if payment.is_recurring and not payment.is_first_recurring:
        await message.answer("⭐ Подписка продлена на месяц. Спасибо!")
        return

    await message.answer(
        "Готово, доступ открыт! 🎉\n\n"
        "Всё на месте: фото еды, голосовые, тренировки, замеры и прогресс.\n"
        "Отменить подписку можно в любой момент в настройках Telegram."
    )


@router.message(Command("admin"))
async def admin_stats(message: Message) -> None:
    """Сводка для владельца: сколько людей и звёзд."""
    if message.from_user.id not in config.ADMIN_IDS:
        return   # для остальных команды словно не существует

    async with get_session() as session:
        data = await stats(session)

    await message.answer(
        "📊 Подписки\n\n"
        f"Всего людей: {data['total']}\n"
        f"Платят сейчас: {data['active']}\n"
        f"На пробном: {data['trial']}\n"
        f"С автопродлением: {data['recurring']}\n"
        f"Закончилась: {data['expired']}\n\n"
        f"Платили хоть раз: {data['payers']}\n"
        f"Звёзд за 30 дней: {data['stars_30d']} ⭐\n\n"
        "Выдать доступ вручную: /grant ID ДНЕЙ"
    )


@router.message(Command("grant"))
async def grant_access(message: Message) -> None:
    """Выдать доступ вручную — например, подруге или за отзыв."""
    if message.from_user.id not in config.ADMIN_IDS:
        return

    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Формат: /grant ID ДНЕЙ\nНапример: /grant 123456789 30")
        return

    user_id, days = int(parts[1]), int(parts[2])
    async with get_session() as session:
        subscription = await activate(
            session, user_id, days=days, source=SubscriptionSource.MANUAL
        )

    await message.answer(
        f"Выдано {days} дней пользователю {user_id}.\n"
        f"Доступ до {subscription.expires_at:%d.%m.%Y}."
    )
    try:
        await message.bot.send_message(
            user_id, f"🎁 Тебе открыли доступ на {days} дней. Заходи в приложение!"
        )
    except Exception:
        logger.info("Не получилось уведомить пользователя %s о выданном доступе", user_id)
