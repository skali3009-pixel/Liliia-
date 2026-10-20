import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

import config
import scheduler
from models import Subscription, SubscriptionSource, SubscriptionStatus, Meal, User
from services import subscription_end as E
from services.subscriptions import now
from tests.test_onboarding_flow import стенд as database, ОНА as UID


def test_expired_account_gets_one_factual_report_and_stays_silent(monkeypatch):
    monkeypatch.setattr(config, "PAYWALL", True)
    async def scenario():
        async with database(monkeypatch) as maker:
            from handlers import onboarding as O
            monkeypatch.setattr(E, "get_session", O.get_session)
            monkeypatch.setattr(scheduler, "get_session", O.get_session)
            end = now() - timedelta(minutes=1)
            async with maker() as session:
                session.add(Subscription(user_id=UID, status=SubscriptionStatus.ACTIVE,
                    source=SubscriptionSource.PLATEGA, expires_at=end))
                session.add(Meal(user_id=UID, name="Test meal", calories=100,
                                 logged_at=end-timedelta(days=1)))
                session.add(Meal(user_id=UID, name="Old meal", calories=100,
                                 logged_at=end-timedelta(days=31)))
                await session.commit()
            assert not await scheduler.product_messages_allowed(UID)
            bot = AsyncMock()
            await E.send_final_reports(bot)
            await E.send_final_reports(bot)
            bot.send_message.assert_awaited_once()
            text = bot.send_message.call_args.args[1]
            assert "1 записей за 1 дн." in text
            assert "недостаточно" in text and "остановлены" in text
            # A renewal suppresses the old notice and restores reminders.
            async with maker() as session:
                from sqlalchemy import select
                sub = (await session.scalars(select(Subscription))).one()
                sub.expires_at = now() + timedelta(days=30)
                sub.status = SubscriptionStatus.ACTIVE
                await session.commit()
            assert await scheduler.product_messages_allowed(UID)
            await E.send_final_reports(bot)
            bot.send_message.assert_awaited_once()
    asyncio.run(scenario())


def test_never_paid_account_does_not_receive_expiry_message(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            from handlers import onboarding as O
            monkeypatch.setattr(E, "get_session", O.get_session)
            async with maker() as session:
                session.add(Subscription(user_id=UID, status=SubscriptionStatus.EXPIRED,
                    source=SubscriptionSource.TRIAL, expires_at=now()-timedelta(minutes=1)))
                await session.commit()
            bot = AsyncMock()
            await E.send_final_reports(bot)
            bot.send_message.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("job,source", [
    ("send_due_reminders", "collect_due_reminders"),
    ("send_smart_nudges", "notifications.due"),
    ("send_comebacks", "comeback.due"),
    ("send_unfinished", "unfinished.due"),
    ("send_step_results", "step_results.due"),
])
def test_every_scheduled_product_path_checks_access(monkeypatch, job, source):
    from types import SimpleNamespace
    async def scenario():
        async with database(monkeypatch):
            from handlers import onboarding as O
            monkeypatch.setattr(scheduler, "get_session", O.get_session)
            denied = AsyncMock(return_value=False)
            monkeypatch.setattr(scheduler, "product_messages_allowed", denied)
            item = SimpleNamespace(user_id=UID)
            rows = [(SimpleNamespace(id=UID), None, None)] if job == "send_smart_nudges" else [item]
            if "." in source:
                module, name = source.split(".")
                monkeypatch.setattr(getattr(scheduler, module), name, AsyncMock(return_value=rows))
            else:
                monkeypatch.setattr(scheduler, source, AsyncMock(return_value=rows))
            bot = AsyncMock()
            await getattr(scheduler, job)(bot)
            denied.assert_awaited_once_with(UID)
            bot.send_message.assert_not_awaited()
    asyncio.run(scenario())
