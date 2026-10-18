"""Settlement through HTTP, outbox retry and authenticated renewal after expiry."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

import config
from models import PlategaOrder, PlategaNotice, PlategaCallback, Payment, Subscription, User
from services import platega
from services.subscriptions import now, _aware
from tests.test_platega import database
from tests.test_webapp_auth import make_init_data
from webapp.server import create_app


def test_missing_callback_is_recovered_without_user_click(monkeypatch):
    monkeypatch.setattr(platega, "configured", lambda: True)
    async def run():
        async with database(monkeypatch) as maker:
            tx = str(uuid4())
            async with maker() as s:
                s.add(PlategaOrder(id="missed", user_id=501, transaction_id=tx,
                    status="PENDING", created_at=now()))
                await s.commit()
            request = AsyncMock(return_value={"id": tx, "payload": "missed", "status": "CONFIRMED",
                "paymentDetails": {"amount": 490, "currency": "RUB"}})
            monkeypatch.setattr(platega, "api", request)
            bot = SimpleNamespace(send_message=AsyncMock())
            await platega.reconcile_pending(bot)
            await platega.reconcile_pending(bot)
            request.assert_awaited_once_with("GET", "/transaction/" + tx)
            bot.send_message.assert_awaited_once()
            buttons = bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard
            assert any(b.callback_data == "first:begin" for row in buttons for b in row)
            async with maker() as s:
                order = await s.get(PlategaOrder, "missed")
                assert order.status == "CONFIRMED"
                assert order.applied_via == "scheduled_check"
                assert order.callback_verified_at is None
                assert len((await s.execute(select(Payment))).scalars().all()) == 1
    asyncio.run(run())


def test_pending_recovery_continues_after_failure_and_backs_off(monkeypatch):
    monkeypatch.setattr(platega, "configured", lambda: True)
    async def run():
        async with database(monkeypatch) as maker:
            ids = [str(uuid4()), str(uuid4())]
            async with maker() as s:
                for i, tx in enumerate(ids):
                    s.add(PlategaOrder(id=str(i), user_id=501, transaction_id=tx,
                        status="PENDING", created_at=now()))
                s.add(PlategaOrder(id="uncertain", user_id=501, status="CREATING", created_at=now()))
                await s.commit()
            check = AsyncMock(side_effect=[platega.PaymentError("timeout"), "PENDING"])
            monkeypatch.setattr(platega, "reconcile", check)
            await platega.reconcile_pending(None)
            await platega.reconcile_pending(None)
            assert check.await_count == 2
            async with maker() as s:
                for i in range(2):
                    assert (await s.get(PlategaOrder, str(i))).checked_at is not None
                assert (await s.get(PlategaOrder, "uncertain")).checked_at is None
    asyncio.run(run())


def test_real_callback_path_grants_notifies_once_and_preserves_source(monkeypatch):
    monkeypatch.setattr(config, "PLATEGA_MERCHANT_ID", "merchant")
    monkeypatch.setattr(config, "PLATEGA_SECRET", "secret")
    async def run():
        async with database(monkeypatch) as maker:
            tx = str(uuid4())
            expiry = now() + timedelta(days=5)
            async with maker() as s:
                s.add(Subscription(user_id=501, expires_at=expiry, status="active"))
                s.add(PlategaOrder(id="paid", user_id=501, transaction_id=tx, created_at=now()))
                await s.commit()
            remote = {"id": tx, "payload": "paid", "status": "CONFIRMED", "paymentDetails": {"amount": 490, "currency": "RUB"}}
            monkeypatch.setattr(platega, "api", AsyncMock(return_value=remote))
            bot = SimpleNamespace(send_message=AsyncMock())
            async with TestClient(TestServer(create_app(bot))) as client:
                for key in ("id", "Id"):
                    response = await client.post("/payments/platega/callback", json={key: tx, "status": "PENDING"},
                        headers={"X-MerchantId": "merchant", "X-Secret": "secret"})
                    assert response.status == 200
            # A later manual check cannot change attribution or add days again.
            await platega.check_order("paid", 501, source="bot_check", bot=bot)
            async with maker() as s:
                sub = (await s.execute(select(Subscription))).scalar_one()
                assert _aware(sub.expires_at) == expiry + timedelta(days=30)
                assert len((await s.execute(select(Payment))).scalars().all()) == 1
                order = await s.get(PlategaOrder, "paid")
                assert order.applied_via == "callback" and order.callback_verified_at
                receipts = (await s.execute(select(PlategaCallback))).scalars().all()
                assert len(receipts) == 2 and {r.result for r in receipts} == {"CONFIRMED"}
                assert (await s.get(PlategaNotice, "paid")).sent_at
            bot.send_message.assert_awaited_once()
            assert "Доступ до" in bot.send_message.call_args.args[1]
    asyncio.run(run())


def test_delivery_failure_keeps_access_and_retries_from_durable_outbox(monkeypatch):
    async def run():
        async with database(monkeypatch) as maker:
            tx = str(uuid4())
            async with maker() as s:
                s.add(PlategaOrder(id="retry", user_id=501, transaction_id=tx, created_at=now()))
                await s.commit()
            monkeypatch.setattr(platega, "api", AsyncMock(return_value={"id": tx, "payload": "retry", "status": "CONFIRMED",
                "paymentDetails": {"amount": 490, "currency": "RUB"}}))
            bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimeoutError()))
            assert await platega.reconcile(tx, source="callback", bot=bot) == "CONFIRMED"
            async with maker() as s:
                assert (await s.get(PlategaOrder, "retry")).applied_at
                notice = await s.get(PlategaNotice, "retry")
                assert not notice.sent_at and notice.attempts == 1
                notice.next_attempt_at = now() - timedelta(seconds=1)
                await s.commit()
            bot.send_message = AsyncMock()
            await platega.retry_notices(bot)
            await platega.retry_notices(bot)
            bot.send_message.assert_awaited_once()
            async with maker() as s:
                assert len((await s.execute(select(Payment))).scalars().all()) == 1
                assert (await s.get(PlategaNotice, "retry")).sent_at
    asyncio.run(run())


def test_legacy_paid_order_replay_sends_confirmation_without_more_days(monkeypatch):
    async def run():
        async with database(monkeypatch) as maker:
            tx, applied, expiry = str(uuid4()), now() - timedelta(hours=1), now() + timedelta(days=29)
            async with maker() as s:
                s.add(Subscription(user_id=501, expires_at=expiry, status="active"))
                s.add(PlategaOrder(id="legacy", user_id=501, transaction_id=tx, created_at=applied,
                    applied_at=applied, status="CONFIRMED"))
                s.add(Payment(user_id=501, amount=1, currency="RUB", days=30, charge_id="platega:" + tx))
                await s.commit()
            monkeypatch.setattr(platega, "api", AsyncMock(return_value={"id": tx, "payload": "legacy", "status": "CONFIRMED",
                "paymentDetails": {"amount": 490, "currency": "RUB"}}))
            bot = SimpleNamespace(send_message=AsyncMock())
            for _ in range(2):
                assert await platega.reconcile(tx, source="diagnostic_replay", bot=bot) == "CONFIRMED"
            async with maker() as s:
                assert _aware((await s.execute(select(Subscription))).scalar_one().expires_at) == expiry
                order = await s.get(PlategaOrder, "legacy")
                assert order.applied_via is None and order.callback_verified_at is None
                assert _aware(order.applied_at) == applied
                assert len((await s.execute(select(Payment))).scalars().all()) == 1
            bot.send_message.assert_awaited_once()
    asyncio.run(run())


def test_callback_failure_is_recorded_and_asks_provider_to_retry(monkeypatch):
    monkeypatch.setattr(config, "PLATEGA_MERCHANT_ID", "merchant")
    monkeypatch.setattr(config, "PLATEGA_SECRET", "secret")
    monkeypatch.setattr(platega, "api", AsyncMock(side_effect=platega.PaymentError("timeout")))
    async def run():
        async with database(monkeypatch) as maker, TestClient(TestServer(create_app())) as client:
            headers = {"X-MerchantId": "merchant", "X-Secret": "secret"}
            assert (await client.post("/payments/platega/callback", json={"id": "bad"}, headers=headers)).status == 400
            assert (await client.post("/payments/platega/callback", json={"id": str(uuid4())}, headers=headers)).status == 503
            async with maker() as s:
                receipt = (await s.execute(select(PlategaCallback))).scalar_one()
                assert receipt.result == "VERIFY_FAILED"
                assert not (await s.execute(select(Payment))).scalars().all()
    asyncio.run(run())


def test_miniapp_expired_user_can_buy_only_own_standard_plan_and_status_is_read_only(monkeypatch):
    import webapp.api as api_module
    monkeypatch.setattr(config, "PAYWALL", True)
    monkeypatch.setattr(config, "PLATEGA_ENABLED", False)
    monkeypatch.setattr(config, "PLATEGA_TEST_USER_IDS", {501})
    monkeypatch.setattr(config, "PLATEGA_MERCHANT_ID", "merchant")
    monkeypatch.setattr(config, "PLATEGA_SECRET", "secret")
    async def run():
        async with database(monkeypatch) as maker:
            monkeypatch.setattr(api_module, "get_session", platega.get_session)
            headers = {"X-Telegram-Init-Data": make_init_data(token=config.BOT_TOKEN, user={"id": 501, "first_name": "Test"})}
            tx = str(uuid4())
            remote = AsyncMock(return_value={"transactionId": tx, "url": "https://pay.platega.io/?id=test"})
            monkeypatch.setattr(platega, "api", remote)
            async with maker() as s:
                s.add(User(id=502, age=25, onboarding_completed=True))
                s.add(Subscription(user_id=501, expires_at=now() - timedelta(days=1)))
                s.add(PlategaOrder(id="other", user_id=502, transaction_id=str(uuid4()), created_at=now()))
                await s.commit()
            async with TestClient(TestServer(create_app())) as client:
                assert (await client.get("/api/subscription")).status == 401
                assert (await client.post("/api/platega/order")).status == 401
                response = await client.get("/api/subscription", headers=headers)
                view = await response.json()
                assert response.status == 200 and not view["access"]["allowed"] and view["checkout_enabled"]
                remote.assert_not_awaited()
                assert (await client.get("/api/profile", headers=headers)).status == 402
                response = await client.post("/api/platega/check", json={"order_id": "other"}, headers=headers)
                assert response.status == 409
                remote.assert_not_awaited()
                response = await client.post("/api/platega/order", json={"amount": 1, "user_id": 502}, headers=headers)
                order = await response.json()
                assert response.status == 200 and order["amount"] == 490 and order["days"] == 30
                assert remote.call_args.args[2]["metadata"]["userId"] == "501"
                assert remote.call_args.args[2]["paymentDetails"]["amount"] == 490
                remote.reset_mock()
                response = await client.get("/api/subscription?order_id=" + order["id"], headers=headers)
                assert (await response.json())["order"]["status"] == "PENDING"
                remote.assert_not_awaited()
                assert response.headers["Cache-Control"] == "no-store"
                foreign_headers = {"X-Telegram-Init-Data": make_init_data(token=config.BOT_TOKEN, user={"id": 502, "first_name": "Other"})}
                response = await client.get("/api/subscription?order_id=" + order["id"], headers=foreign_headers)
                other_view = await response.json()
                assert other_view["order"] is None and not other_view["checkout_enabled"]
                assert (await client.post("/api/platega/order", json={}, headers=foreign_headers)).status == 409
                remote.assert_not_awaited()
                remote.return_value = {"id": tx, "payload": order["id"], "status": "CONFIRMED",
                    "paymentDetails": {"amount": 490, "currency": "RUB"}}
                response = await client.post("/api/platega/check", json={"order_id": order["id"]}, headers=headers)
                view = await response.json()
                assert response.status == 200 and view["access"]["allowed"] and view["checked_status"] == "CONFIRMED"
                assert "Доступ до" in view["subscription_text"]
                async with maker() as s:
                    assert (await s.get(PlategaOrder, order["id"])).applied_via == "web_check"
    asyncio.run(run())
