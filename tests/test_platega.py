import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import config
from models import Base, User, Subscription, Payment, PlategaOrder
from services import platega
from services.subscriptions import _aware, now
from services.subscriptions import stats
from webapp.server import create_app


def test_pilot_does_not_enable_public_checkout(monkeypatch):
    monkeypatch.setattr(config, "PLATEGA_ENABLED", False)
    monkeypatch.setattr(config, "PLATEGA_TEST_USER_IDS", {501})
    monkeypatch.setattr(config, "PLATEGA_MERCHANT_ID", "merchant")
    monkeypatch.setattr(config, "PLATEGA_SECRET", "secret")
    assert platega.enabled(501)
    assert not platega.enabled(502)
    assert not platega.enabled()


@asynccontextmanager
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    @asynccontextmanager
    async def session():
        async with maker() as s:
            yield s
    monkeypatch.setattr(platega, "get_session", session)
    async with maker() as s:
        from services.legal import LEGAL_VERSION
        s.add(User(id=501, age=25, onboarding_completed=True,
                   legal_version=LEGAL_VERSION, legal_accepted_at=now()))
        await s.commit()
    try:
        yield maker
    finally:
        await engine.dispose()


def test_settlement_replay_amount_owner_and_refund(monkeypatch):
    async def run():
        async with database(monkeypatch) as maker:
            transaction = str(uuid4())
            expiry = now() + timedelta(days=5)
            async with maker() as s:
                s.add(Subscription(user_id=501, expires_at=expiry))
                s.add(PlategaOrder(id="order", user_id=501, transaction_id=transaction, created_at=now()))
                await s.commit()
            data = {"id": transaction, "payload": "order", "status": "CONFIRMED",
                    "paymentDetails": {"amount": 490, "currency": "RUB"}}
            monkeypatch.setattr(platega, "api", AsyncMock(return_value=data))
            with pytest.raises(platega.PaymentError):
                await platega.check_order("order", 502)
            data["paymentDetails"]["amount"] = 1
            with pytest.raises(platega.PaymentError):
                await platega.reconcile(transaction)
            async with maker() as s:
                assert not (await s.execute(select(Payment))).scalars().all()
            data["paymentDetails"]["amount"] = 490
            assert await platega.reconcile(transaction) == "CONFIRMED"
            assert await platega.reconcile(transaction) == "CONFIRMED"
            async with maker() as s:
                sub = (await s.execute(select(Subscription))).scalar_one()
                assert _aware(sub.expires_at) == expiry + timedelta(days=30)
                payment = (await s.execute(select(Payment))).scalar_one()
                assert payment.currency == "RUB" and payment.amount == 490
                report = await stats(s)
                assert report["rub_30d"] == 490 and report["stars_30d"] == 0
            data["status"] = "CHARGEBACKED"
            await platega.reconcile(transaction)
            await platega.reconcile(transaction)
            data["status"] = "CONFIRMED"
            assert await platega.reconcile(transaction) == "CHARGEBACKED"
            async with maker() as s:
                sub = (await s.execute(select(Subscription))).scalar_one()
                assert _aware(sub.expires_at) == expiry
                assert (await s.execute(select(Payment))).scalar_one().refunded
    asyncio.run(run())


@pytest.mark.parametrize("field,value", [("age", 16), ("legal_version", "old"), ("onboarding_completed", False)])
def test_ineligible_profile_cannot_create_payment(monkeypatch, field, value):
    monkeypatch.setattr(platega, "enabled", lambda *args: True)
    request = AsyncMock()
    monkeypatch.setattr(platega, "api", request)
    async def run():
        async with database(monkeypatch) as maker:
            async with maker() as s:
                user = await s.get(User, 501)
                setattr(user, field, value)
                await s.commit()
            with pytest.raises(platega.PaymentError):
                await platega.create_order(501)
            request.assert_not_awaited()
    asyncio.run(run())


def test_order_reuses_link_and_never_retries_uncertain_post(monkeypatch):
    monkeypatch.setattr(platega, "enabled", lambda *args: True)
    async def run():
        async with database(monkeypatch):
            request = AsyncMock(return_value={"transactionId": str(uuid4()), "url": "https://pay.platega.io/?id=test"})
            monkeypatch.setattr(platega, "api", request)
            first = await platega.create_order(501)
            second = await platega.create_order(501)
            assert first.id == second.id
            assert request.await_count == 1
        async with database(monkeypatch):
            request = AsyncMock(side_effect=platega.PaymentError("timeout"))
            monkeypatch.setattr(platega, "api", request)
            for _ in range(2):
                with pytest.raises(platega.PaymentError):
                    await platega.create_order(501)
            assert request.await_count == 1
    asyncio.run(run())


def test_callback_authentication_precedes_api_and_ignores_body_status(monkeypatch):
    monkeypatch.setattr(config, "PLATEGA_MERCHANT_ID", "merchant")
    monkeypatch.setattr(config, "PLATEGA_SECRET", "secret")
    check = AsyncMock(return_value="PENDING")
    monkeypatch.setattr(platega, "reconcile", check)
    async def run():
        async with TestClient(TestServer(create_app())) as client:
            body = {"id": str(uuid4()), "status": "CONFIRMED", "amount": 490}
            result = await client.post("/payments/platega/callback", json=body)
            assert result.status == 401
            check.assert_not_awaited()
            result = await client.post("/payments/platega/callback", json=body,
                                      headers={"X-MerchantId": "merchant", "X-Secret": "secret"})
            assert result.status == 200
            check.assert_awaited_once_with(body["id"])
    asyncio.run(run())
