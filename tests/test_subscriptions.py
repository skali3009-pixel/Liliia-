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
    grandfather_existing,
    grant_lifetime,
    now,
    stats,
)

USER_ID = 501


@contextlib.asynccontextmanager
async def paywall(enabled: bool = True):
    """Платный доступ включён/выключен на время проверки."""
    before = config.PAYWALL
    config.PAYWALL = enabled
    try:
        yield
    finally:
        config.PAYWALL = before


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


def test_existing_users_stay_free_forever_when_the_paywall_turns_on():
    """Человек пришёл, когда бот был бесплатным. Закрывать ему доступ нельзя."""
    async def scenario():
        async with db() as session, paywall():
            assert await grandfather_existing(session) == 1

            access = await check_access(session, USER_ID)
            assert access.allowed
            assert access.is_lifetime
            assert access.expires_at is None

            # Граница проводится один раз: повторный запуск никого не трогает.
            assert await grandfather_existing(session) == 0
    run(scenario)


def test_grandfathering_covers_people_who_only_pressed_start():
    """Анкету не дозаполнил — но бот-то уже был обещан бесплатным."""
    async def scenario():
        async with db() as session, paywall():
            session.add(User(id=777, onboarding_completed=False))
            await session.commit()

            await grandfather_existing(session)
            assert (await check_access(session, 777)).is_lifetime
    run(scenario)


def test_nothing_happens_while_the_bot_is_free_for_everyone():
    """Пока оплаты нет, делить людей не на что — и границу ставить рано."""
    async def scenario():
        async with db() as session, paywall(False):
            assert await grandfather_existing(session) == 0
            assert (await check_access(session, USER_ID)).is_lifetime is False
    run(scenario)


def test_newcomers_after_the_paywall_pay_as_usual():
    """Вечный доступ — только тем, кто был раньше. Остальные платят."""
    async def scenario():
        async with db() as session, paywall():
            await grandfather_existing(session)

            session.add(User(id=778, onboarding_completed=True))
            await session.commit()
            subscription = await ensure_trial(session, 778)
            assert subscription.lifetime is False

            subscription.expires_at = now() - timedelta(days=1)
            await session.commit()
            assert (await check_access(session, 778)).allowed is False
    run(scenario)


def test_lifetime_access_never_expires_and_never_nags():
    """Ни «срок вышел», ни «скоро закончится» к вечному доступу не относятся."""
    async def scenario():
        async with db() as session:
            await grant_lifetime(session, [USER_ID])

            assert await expire_overdue(session) == []
            assert await expiring_soon(session, days=3) == []
            assert (await check_access(session, USER_ID)).allowed
    run(scenario)


def test_owner_can_open_lifetime_access_to_a_person_whose_time_ran_out():
    async def scenario():
        async with db() as session:
            subscription = await ensure_trial(session, USER_ID)
            subscription.expires_at = now() - timedelta(days=10)
            subscription.status = SubscriptionStatus.EXPIRED
            await session.commit()
            assert (await check_access(session, USER_ID)).allowed is False

            assert await grant_lifetime(session, [USER_ID]) == 1
            assert (await check_access(session, USER_ID)).is_lifetime

            # Второй раз выдавать нечего.
            assert await grant_lifetime(session, [USER_ID]) == 0
    run(scenario)


def test_lifetime_people_are_counted_apart_from_payers():
    """Вечный доступ — не выручка, в отчёте владельца он отдельной строкой."""
    async def scenario():
        async with db() as session:
            await grant_lifetime(session, [USER_ID])
            data = await stats(session)
            assert data["lifetime"] == 1
            assert data["active"] == 0
            assert data["expired"] == 0
    run(scenario)
