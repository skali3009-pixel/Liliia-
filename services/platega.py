"""One-off RUB checkout. No access is granted from redirects or callback data.

The callback is authenticated, then transaction details are fetched from Platega.
Order state, ledger and access are committed together under the user row lock.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import aiohttp
from sqlalchemy import select

import config
from db import get_session
from models import Payment, PlategaOrder, Subscription, SubscriptionSource, SubscriptionStatus, User
from services.subscriptions import _aware, now

PRICE = 490
DAYS = 30
RETURN_URL = "https://t.me/Scalia_fit_food_bot"


class PaymentError(Exception):
    pass


def configured():
    return bool(config.PLATEGA_MERCHANT_ID and config.PLATEGA_SECRET)


def enabled(user_id=None):
    return configured() and (config.PLATEGA_ENABLED or user_id in config.PLATEGA_TEST_USER_IDS)


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


async def reconcile(transaction_id, *, user_id=None):
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
                     and Decimal(str(details["amount"])) == Decimal(order.amount))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            valid = False
        if not valid:
            raise PaymentError("Сумма или реквизиты платежа не совпали.")
        status = data.get("status")
        if status not in {"PENDING", "CONFIRMED", "CANCELED", "CHARGEBACKED"}:
            raise PaymentError("Неизвестный статус платежа.")
        order.transaction_id = transaction_id
        sub = (await session.execute(select(Subscription).where(Subscription.user_id == order.user_id).with_for_update())).scalar_one_or_none()
        if status == "CONFIRMED" and order.applied_at is None and order.status != "CHARGEBACKED":
            if sub is None:
                sub = Subscription(user_id=order.user_id, expires_at=now(), trial_used=True)
                session.add(sub)
            if not sub.lifetime:
                sub.expires_at = max(_aware(sub.expires_at), now()) + timedelta(days=order.days)
                sub.status = SubscriptionStatus.ACTIVE
                sub.source = SubscriptionSource.PLATEGA
                sub.is_recurring = False
                sub.warned_at = None
            session.add(Payment(user_id=order.user_id, amount=order.amount, currency="RUB",
                                days=order.days, charge_id="platega:" + transaction_id))
            order.applied_at = now()
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
        await session.commit()
        return order.status


async def check_order(order_id, user_id):
    async with get_session() as session:
        order = await session.get(PlategaOrder, order_id)
        if not order or order.user_id != user_id:
            raise PaymentError("Платёж не найден.")
        transaction_id = order.transaction_id
    if not transaction_id:
        raise PaymentError("Счёт ещё проверяется. Напиши /problem, если ожидание затянулось.")
    return await reconcile(transaction_id, user_id=user_id)
