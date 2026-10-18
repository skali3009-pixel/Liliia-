"""One-off RUB checkout. No access is granted from redirects or callback data.

The callback is authenticated, then transaction details are fetched from Platega.
Order state, ledger and access are committed together under the user row lock.
"""
from datetime import timedelta
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import aiohttp
from sqlalchemy import select, or_

import config
from db import get_session
from models import Payment, PlategaOrder, PlategaNotice, Subscription, SubscriptionSource, SubscriptionStatus, User
from services.subscriptions import _aware, now

PRICE = 490
DAYS = 30
RETURN_URL = "https://t.me/Scalia_fit_food_bot"
logger = logging.getLogger(__name__)


class PaymentError(Exception):
    pass


def configured():
    return bool(config.PLATEGA_MERCHANT_ID and config.PLATEGA_SECRET)


def enabled(user_id=None):
    return configured() and (config.PLATEGA_ENABLED or user_id in config.PLATEGA_TEST_USER_IDS)


def amount_matches(details, data, expected):
    """Only server-fetched totals: some methods add the payer's commission."""
    total = Decimal(str(details["amount"]))
    fee = Decimal(str(data.get("comission", 0)))
    principal = Decimal(expected)
    return (total.is_finite() and fee.is_finite() and fee >= 0
            and (total == principal or total - fee == principal))


async def api(method, path, body=None):
    if not configured():
        raise PaymentError("Оплата ещё не настроена.")
    headers = {"X-MerchantId": config.PLATEGA_MERCHANT_ID, "X-Secret": config.PLATEGA_SECRET}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as client:
            async with client.request(method, "https://app.platega.io" + path,
                                      headers=headers, json=body, allow_redirects=False) as response:
                if response.status != 200:
                    raise PaymentError("Платёжный сервис временно недоступен.")
                data = await response.json()
                if not isinstance(data, dict):
                    raise ValueError()
                return data
    except (aiohttp.ClientError, TimeoutError, ValueError):
        # Never put response bodies or authorization headers in logs/errors.
        raise PaymentError("Не удалось получить ответ платёжного сервиса.") from None


async def create_order(user_id, *, one_ruble_test=False):
    if one_ruble_test and user_id not in config.PLATEGA_TEST_USER_IDS:
        raise PaymentError("Тестовый платёж недоступен для этого аккаунта.")
    amount = 1 if one_ruble_test else PRICE
    if not enabled(user_id):
        raise PaymentError("Оплата пока не подключена.")
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
        if not user or not user.onboarding_completed or not user.age or user.age < 18:
            raise PaymentError("Сначала заполни взрослый профиль через /start.")
        from services.legal import LEGAL_VERSION
        if user.legal_version != LEGAL_VERSION or not user.legal_accepted_at:
            raise PaymentError("Перед покупкой прими актуальные условия через /start.")
        sub = (await session.execute(select(Subscription).where(Subscription.user_id == user_id))).scalar_one_or_none()
        if sub and sub.lifetime:
            raise PaymentError("У тебя бессрочный доступ — платить не нужно.")
        order = (await session.execute(select(PlategaOrder).where(
            PlategaOrder.user_id == user_id,
            PlategaOrder.amount == amount,
            PlategaOrder.status.in_(["CREATING", "PENDING"])
        ).order_by(PlategaOrder.created_at.desc()).limit(1))).scalar_one_or_none()
        if order:
            if order.url:
                return order
            raise PaymentError("Предыдущий счёт ещё проверяется. Не оплачивай повторно; напиши /problem.")
        order = PlategaOrder(id=uuid4().hex, user_id=user_id, amount=amount, days=DAYS, created_at=now())
        session.add(order)
        await session.commit()
        order_id = order.id
    # No retry on POST: an uncertain response can already mean a real order.
    data = await api("POST", "/v2/transaction/process", {
        "paymentDetails": {"amount": amount, "currency": "RUB"},
        "description": "AURA — тест оплаты 1 рубль, 30 дней" if one_ruble_test else "AURA — доступ на 30 дней, без автопродления",
        "return": RETURN_URL, "failedUrl": RETURN_URL,
        "payload": order_id, "metadata": {"userId": str(user_id)},
    })
    try:
        transaction_id = str(UUID(data["transactionId"]))
        url = data["url"]
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "pay.platega.io" or parsed.username or parsed.password:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise PaymentError("Не удалось проверить платёжную ссылку. Напиши /problem.") from None
    async with get_session() as session:
        order = (await session.execute(select(PlategaOrder).where(PlategaOrder.id == order_id).with_for_update())).scalar_one()
        if order.transaction_id and order.transaction_id != transaction_id:
            raise PaymentError("Номер платежа не совпал.")
        order.transaction_id = transaction_id
        order.url = url
        if order.status == "CREATING":
            order.status = "PENDING"
        await session.commit()
        return order


async def reconcile(transaction_id, *, user_id=None, source="operator", bot=None):
    try:
        transaction_id = str(UUID(transaction_id))
    except (ValueError, TypeError, AttributeError):
        raise PaymentError("Неверный номер платежа.") from None
    data = await api("GET", "/transaction/" + transaction_id)
    async with get_session() as session:
        # Payload is generated by our server, not accepted from the callback.
        order = await session.get(PlategaOrder, data.get("payload", ""))
        if not order or (user_id is not None and order.user_id != user_id):
            raise PaymentError("Платёж не найден.")
        await session.execute(select(User).where(User.id == order.user_id).with_for_update())
        await session.refresh(order)
        try:
            details = data["paymentDetails"]
            valid = (str(UUID(data["id"])) == transaction_id
                     and (not order.transaction_id or order.transaction_id == transaction_id)
                     and details["currency"] == "RUB"
                     and amount_matches(details, data, order.amount))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            valid = False
        if not valid:
            raise PaymentError("Сумма или реквизиты платежа не совпали.")
        status = data.get("status")
        if status not in {"PENDING", "CONFIRMED", "CANCELED", "CHARGEBACKED"}:
            raise PaymentError("Неизвестный статус платежа.")
        order.transaction_id = transaction_id
        if source == "callback":
            order.callback_verified_at = now()
        sub = (await session.execute(select(Subscription).where(Subscription.user_id == order.user_id).with_for_update())).scalar_one_or_none()
        if status == "CONFIRMED" and order.applied_at is None and order.status != "CHARGEBACKED":
            if sub is None:
                sub = Subscription(user_id=order.user_id, expires_at=now(), trial_used=True)
                session.add(sub)
            if not sub.lifetime:
                base = now() if config.TRIAL_DAYS <= 0 and sub.status == SubscriptionStatus.TRIAL else max(_aware(sub.expires_at), now())
                sub.expires_at = base + timedelta(days=order.days)
                sub.status = SubscriptionStatus.ACTIVE
                sub.source = SubscriptionSource.PLATEGA
                sub.is_recurring = False
                sub.warned_at = None
            session.add(Payment(user_id=order.user_id, amount=order.amount, currency="RUB",
                                days=order.days, charge_id="platega:" + transaction_id))
            order.applied_at = now()
            order.applied_via = source
            order.status = status
        elif status == "CHARGEBACKED" and order.status != "CHARGEBACKED":
            if order.applied_at:
                payment = (await session.execute(select(Payment).where(Payment.charge_id == "platega:" + transaction_id))).scalar_one()
                payment.refunded = True
                if sub and not sub.lifetime:
                    sub.expires_at = _aware(sub.expires_at) - timedelta(days=order.days)
                    if _aware(sub.expires_at) <= now():
                        sub.status = SubscriptionStatus.EXPIRED
            order.status = status
        elif order.applied_at is None and order.status != "CHARGEBACKED":
            order.status = status
        # Also cover verified payments made before the outbox was deployed.
        # This does not scan or message historical users: only this verified order.
        if order.status == "CONFIRMED" and sub and not await session.get(PlategaNotice, order.id):
            session.add(PlategaNotice(order_id=order.id,
                expires_at=None if sub.lifetime else sub.expires_at, next_attempt_at=now()))
        await session.commit()
        result, order_id = order.status, order.id
    if bot is not None:
        await notify_order(bot, order_id)
    return result


async def check_order(order_id, user_id, *, source="operator", bot=None):
    async with get_session() as session:
        order = await session.get(PlategaOrder, order_id)
        if not order or order.user_id != user_id:
            raise PaymentError("Платёж не найден.")
        transaction_id = order.transaction_id
    if not transaction_id:
        raise PaymentError("Счёт ещё проверяется. Напиши /problem, если ожидание затянулось.")
    return await reconcile(transaction_id, user_id=user_id, source=source, bot=bot)


async def reconcile_pending(bot):
    """Recover missed callbacks without charging or requiring a user click.

    A persisted lease rotates the bounded batch fairly, including after failures.
    Do not expire orders locally: only the provider decides their final state.
    """
    if not configured():
        return
    stamp = now()
    async with get_session() as session:
        orders = (await session.execute(select(PlategaOrder).where(
            PlategaOrder.status.in_(["CREATING", "PENDING"]),
            PlategaOrder.transaction_id.is_not(None),
            or_(PlategaOrder.checked_at.is_(None),
                PlategaOrder.checked_at < stamp - timedelta(minutes=2))
        ).order_by(PlategaOrder.checked_at.asc().nullsfirst(), PlategaOrder.created_at)
          .limit(20).with_for_update(skip_locked=True))).scalars().all()
        transactions = [order.transaction_id for order in orders]
        for order in orders:
            order.checked_at = stamp
        await session.commit()
    for transaction_id in transactions:
        try:
            result = await reconcile(transaction_id, source="scheduled_check", bot=bot)
            logger.info("Platega scheduled check %s: %s", transaction_id, result)
        except PaymentError:
            logger.warning("Platega scheduled verification pending: %s", transaction_id)


def expiry_text(expires_at, zone="Europe/Moscow"):
    if expires_at is None:
        return "Доступ бессрочный."
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        tz = ZoneInfo("Europe/Moscow")
    local = _aware(expires_at).astimezone(tz)
    return f"Доступ до {local:%d.%m.%Y, %H:%M} ({tz.key})."


async def subscription_view(user_id, *, order_id=None):
    """Read-only: viewing the page must not reconcile or grant payments."""
    from services.legal import LEGAL_VERSION
    from services.subscriptions import check_access
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise PaymentError("Профиль не найден.")
        access = await check_access(session, user_id)
        eligible = (enabled(user_id) and bool(user.age and user.age >= 18)
                    and user.onboarding_completed and not access.is_lifetime and not access.is_admin)
        legal_ok = user.legal_version == LEGAL_VERSION and bool(user.legal_accepted_at)
        query = select(PlategaOrder).where(PlategaOrder.user_id == user_id)
        if order_id:
            query = query.where(PlategaOrder.id == order_id)
        order = (await session.execute(query.order_by(PlategaOrder.created_at.desc()).limit(1))).scalar_one_or_none()
        text = ("Доступ владельца бессрочный." if access.is_admin else
                expiry_text(access.expires_at, user.timezone) if access.is_lifetime or access.expires_at else
                "Оплаченной подписки пока нет.")
        if access.expires_at and not access.allowed:
            text = text.replace("Доступ до", "Доступ закончился")
        return {"access": access.to_dict(), "subscription_text": text,
                "checkout_enabled": bool(eligible and legal_ok),
                "checkout_note": "Прими актуальные условия через /start в чате AURA." if eligible and not legal_ok else
                    "30 дней — 490 ₽. Без автосписаний. Оставшиеся дни сохранятся." if eligible else
                    "Продажи для этого аккаунта пока не открыты." if not access.is_lifetime and not access.is_admin else "Платить не нужно.",
                "order": order_view(order) if order else None}


def order_view(order):
    return {"id": order.id, "status": order.status, "amount": order.amount,
            "days": order.days, "url": order.url if order.status == "PENDING" else None}


async def notify_order(bot, order_id):
    """Serialize delivery attempts; network failure never rolls back access.

    Telegram has no idempotency key: a process crash after delivery but before
    commit can cause one duplicate. Ordinary retries/callback replays do not.
    """
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
    from aiogram.types import WebAppInfo
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    try:
        async with get_session() as session:
            notice = (await session.execute(select(PlategaNotice).where(
                PlategaNotice.order_id == order_id).with_for_update())).scalar_one_or_none()
            if not notice or notice.sent_at or not notice.next_attempt_at or _aware(notice.next_attempt_at) > now():
                return
            order = await session.get(PlategaOrder, order_id)
            if not order or order.status != "CONFIRMED":
                notice.next_attempt_at = None
                await session.commit()
                return
            user = await session.get(User, order.user_id)
            keyboard = InlineKeyboardBuilder()
            keyboard.button(text="С чего начать", callback_data="first:begin")
            if config.WEBAPP_URL:
                keyboard.button(text="Открыть AURA", web_app=WebAppInfo(url=config.WEBAPP_URL))
            keyboard.button(text="Моя подписка", callback_data="platega:subscription")
            keyboard.adjust(1)
            notice.attempts += 1
            try:
                await bot.send_message(order.user_id,
                    f"✅ Оплата подтверждена. За этот платёж начислено {order.days} дней доступа к AURA.\n"
                    + expiry_text(notice.expires_at, user.timezone) + "\nАвтосписаний нет. Помощь: /problem.",
                    reply_markup=keyboard.as_markup(), request_timeout=15)
            except Exception as error:
                notice.last_error = type(error).__name__
                delay = max(60, error.retry_after) if isinstance(error, TelegramRetryAfter) else min(3600, 60 * 2 ** notice.attempts)
                notice.next_attempt_at = None if isinstance(error, TelegramForbiddenError) or notice.attempts >= 8 else now() + timedelta(seconds=delay)
                logger.warning("Platega notice %s attempt %s: %s", order_id, notice.attempts, notice.last_error)
            else:
                notice.sent_at, notice.next_attempt_at, notice.last_error = now(), None, None
                logger.info("Platega notice sent: %s", order_id)
            await session.commit()
    except Exception as error:
        # Scheduler can retry the durable outbox, including after a restart.
        logger.error("Platega notice pending: %s (%s)", order_id, type(error).__name__)


async def retry_notices(bot):
    async with get_session() as session:
        ids = (await session.execute(select(PlategaNotice.order_id).where(
            PlategaNotice.sent_at.is_(None), PlategaNotice.next_attempt_at <= now()
        ).order_by(PlategaNotice.next_attempt_at).limit(20))).scalars().all()
    for order_id in ids:
        await notify_order(bot, order_id)
