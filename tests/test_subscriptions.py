"""Тесты платного доступа: пробный период, оплата, продление, окончание."""

import asyncio
import contextlib
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from models import Base, Subscription, SubscriptionSource, SubscriptionStatus, User
from services.subscriptions import (
    activate,
    check_access,
    ensure_trial,
    expire_overdue,
    expiring_soon,
    now,
    stats,
)

USER_ID = 501


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(id=USER_ID, onboarding_completed=True))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def test_new_person_gets_a_trial():
    async def scenario():
        async with db() as session:
            await ensure_trial(session, USER_ID)
            access = await check_access(session, USER_ID)

            assert access.allowed
            assert access.is_trial
            assert access.days_left == config.TRIAL_DAYS
    run(scenario)


def test_trial_is_given_once():
    """Второй /start не должен продлевать знакомство ещё на неделю."""
    async def scenario():
        async with db() as session:
            first = await ensure_trial(session, USER_ID)
            first.expires_at = now() - timedelta(days=1)
            await session.commit()

            await ensure_trial(session, USER_ID)
            access = await check_access(session, USER_ID)

            assert access.allowed is False
    run(scenario)


def test_payment_opens_access():
    async def scenario():
        async with db() as session:
            await activate(session, USER_ID, days=30, source=SubscriptionSource.STARS,
                           amount=499, charge_id="ch_1", is_recurring=True)

            access = await check_access(session, USER_ID)
            assert access.allowed
            assert access.status == SubscriptionStatus.ACTIVE
            assert access.is_recurring
            assert 29 <= access.days_left <= 30
    run(scenario)


def test_paying_early_does_not_burn_remaining_days():
    """Оплатила на середине пробного — оставшиеся дни прибавляются, а не теряются."""
    async def scenario():
        async with db() as session:
            await ensure_trial(session, USER_ID)          # 7 дней
            await activate(session, USER_ID, days=30, source=SubscriptionSource.STARS)

            access = await check_access(session, USER_ID)
            assert access.days_left >= 36
    run(scenario)


def test_expired_subscription_closes_access():
    async def scenario():
        async with db() as session:
            subscription = await ensure_trial(session, USER_ID)
            subscription.expires_at = now() - timedelta(hours=1)
            await session.commit()

            access = await check_access(session, USER_ID)
            assert access.allowed is False
            assert access.days_left == 0
    run(scenario)


def test_stranger_without_subscription_has_no_access():
    async def scenario():
        async with db() as session:
            access = await check_access(session, 999999)
            assert access.allowed is False
    run(scenario)


def test_owner_always_has_access(monkeypatch):
    """Иначе владелец не сможет починить собственный бот."""
    monkeypatch.setattr(config, "ADMIN_IDS", {USER_ID})

    async def scenario():
        async with db() as session:
            access = await check_access(session, USER_ID)
            assert access.allowed and access.is_admin
    run(scenario)


def test_overdue_subscriptions_are_marked_once():
    async def scenario():
        async with db() as session:
            subscription = await ensure_trial(session, USER_ID)
            subscription.expires_at = now() - timedelta(days=2)
            await session.commit()

            assert await expire_overdue(session) == [USER_ID]
            # Второй раз тот же человек не должен попасть в рассылку.
            assert await expire_overdue(session) == []
    run(scenario)


def test_warning_goes_only_to_those_without_autopay():
    async def scenario():
        async with db() as session:
            subscription = await ensure_trial(session, USER_ID)
            subscription.expires_at = now() + timedelta(days=2)
            await session.commit()

            assert [s.user_id for s in await expiring_soon(session)] == [USER_ID]

            subscription.is_recurring = True
            await session.commit()
            assert await expiring_soon(session) == []
    run(scenario)


def test_stats_count_people_and_stars():
    async def scenario():
        async with db() as session:
            await activate(session, USER_ID, days=30, source=SubscriptionSource.STARS,
                           amount=499, charge_id="ch_1")

            data = await stats(session)
            assert data["active"] == 1
            assert data["payers"] == 1
            assert data["stars_30d"] == 499
    run(scenario)


@pytest.mark.parametrize("days,expected", [(1, 1), (0, 0)])
def test_days_left_is_never_negative(days, expected):
    async def scenario():
        async with db() as session:
            subscription = await ensure_trial(session, USER_ID)
            subscription.expires_at = now() + timedelta(days=days, minutes=1)
            await session.commit()

            access = await check_access(session, USER_ID)
            assert access.days_left >= expected
    run(scenario)
