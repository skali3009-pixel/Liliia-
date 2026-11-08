"""Бесплатная примерка еды: одна попытка, только новым и только до оплаты."""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (ActivityLevelEnum, Base, GenderEnum, GoalEnum, MarketingEvent,
                    Meal, User)
from services import analytics
from services import demo as demo_module
from services.food_vision import FoodAnalysis, FoodNotRecognized

UID = 771
NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)

ANALYSIS = FoodAnalysis(
    name="Овсянка с бананом", weight_g=280, calories=390, protein_g=12,
    fat_g=9, carbs_g=64, fiber_g=7, confidence="high", comment="",
)


class FakeState:
    def __init__(self):
        self.state = None
        self.cleared = False

    async def set_state(self, state):
        self.state = state

    async def get_state(self):
        return self.state

    async def clear(self):
        self.state = None
        self.cleared = True


class FakeStatus:
    def __init__(self):
        self.text = ""
        self.markup = None

    async def edit_text(self, text, **kwargs):
        self.text = text
        self.markup = kwargs.get("reply_markup")


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.from_user = SimpleNamespace(id=UID)
        self.chat = SimpleNamespace(id=UID)
        self.bot = AsyncMock()
        self.said = []
        self.statuses = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        status = FakeStatus()
        self.statuses.append(status)
        return status


class FakeCallback:
    def __init__(self):
        self.from_user = SimpleNamespace(id=UID)
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text="", **kwargs):
        self.answers.append((text, kwargs))


@contextlib.asynccontextmanager
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def get_session():
        async with maker() as session:
            yield session

    import handlers.demo as handler

    original = handler.get_session
    handler.get_session = get_session
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as session:
            session.add(User(
                id=UID, full_name="Тест", gender=GenderEnum.FEMALE, age=30,
                height_cm=165, current_weight_kg=60,
                goal=GoalEnum.LOSE_WEIGHT,
                activity_level=ActivityLevelEnum.MODERATE,
                onboarding_completed=True,
                promo_started_at=NOW - timedelta(hours=1),
                daily_calories=1600, daily_protein_g=120, daily_fat_g=48,
                daily_carbs_g=160, daily_fiber_g=22, daily_water_ml=2100,
                timezone="Europe/Moscow"))
            await session.commit()
        yield maker
    finally:
        handler.get_session = original
        await engine.dispose()


# --- правила доступа -------------------------------------------------------

def test_demo_is_only_for_new_unpaid_users():
    old = SimpleNamespace(onboarding_completed=True, demo_food_at=None, age=30,
                          promo_started_at=NOW - timedelta(days=5))
    new = SimpleNamespace(onboarding_completed=True, demo_food_at=None, age=30,
                          promo_started_at=NOW - timedelta(hours=1))

    assert demo_module.available(old, allowed=False, now_utc=NOW) is False
    assert demo_module.available(new, allowed=False, now_utc=NOW) is True
    assert demo_module.available(new, allowed=True, now_utc=NOW) is False

    used = SimpleNamespace(onboarding_completed=True, demo_food_at=NOW, age=30,
                           promo_started_at=NOW - timedelta(hours=1))
    assert demo_module.available(used, allowed=False, now_utc=NOW) is False

    minor = SimpleNamespace(onboarding_completed=True, demo_food_at=None, age=17,
                            promo_started_at=NOW - timedelta(hours=1))
    assert demo_module.available(minor, allowed=False, now_utc=NOW) is False


def test_demo_expires_with_the_promo_window():
    new = SimpleNamespace(onboarding_completed=True, demo_food_at=None, age=30,
                          promo_started_at=NOW - timedelta(hours=1))
    late = NOW + demo_module.WINDOW
    assert demo_module.available(new, allowed=False, now_utc=late) is False


def test_demo_messages_are_open_only_in_the_demo_state():
    new = SimpleNamespace(onboarding_completed=True, demo_food_at=None, age=30,
                          promo_started_at=NOW - timedelta(hours=1))
    assert demo_module.message_allowed(
        new, "DemoStates:waiting_food", allowed=False, now_utc=NOW)
    assert not demo_module.message_allowed(
        new, "OnboardingStates:summary", allowed=False, now_utc=NOW)
    assert not demo_module.message_allowed(
        new, "DemoStates:waiting_food", allowed=True, now_utc=NOW)


# --- путь человека ---------------------------------------------------------

def test_successful_demo_uses_the_attempt_and_offers_290(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            import handlers.demo as handler

            async def fake_analyze(text, *, on_usage=None):
                return ANALYSIS

            monkeypatch.setattr(handler, "analyze_text", fake_analyze)
            state, message = FakeState(), FakeMessage("овсянка с бананом")

            await handler.demo_text(message, state)

            status_text = message.statuses[-1].text
            assert "Овсянка с бананом" in status_text
            assert "24%" in status_text
            assert "290" in status_text
            assert any(button.callback_data == "platega:promo290"
                       for row in message.statuses[-1].markup.inline_keyboard
                       for button in row)
            assert state.cleared

            async with maker() as session:
                user = await session.get(User, UID)
                assert user.demo_food_at is not None
                assert (await session.execute(
                    select(func.count()).select_from(Meal))).scalar_one() == 0
                events = (await session.execute(
                    select(MarketingEvent.event))).scalars().all()
                assert analytics.DEMO_DONE in events
    asyncio.run(scenario())


def test_failed_demo_does_not_use_the_attempt(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            import handlers.demo as handler

            async def fake_analyze(text, *, on_usage=None):
                raise FoodNotRecognized("На фото не видно еды.")

            monkeypatch.setattr(handler, "analyze_text", fake_analyze)
            state, message = FakeState(), FakeMessage("что-то непонятное")

            await handler.demo_text(message, state)

            async with maker() as session:
                user = await session.get(User, UID)
                assert user.demo_food_at is None
            assert not state.cleared
            assert "не видно еды" in message.statuses[-1].text
    asyncio.run(scenario())


def test_second_demo_is_refused(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            import handlers.demo as handler

            async with maker() as session:
                user = await session.get(User, UID)
                user.demo_food_at = NOW
                await session.commit()

            state, callback = FakeState(), FakeCallback()
            await handler.start_demo(callback, state)

            from handlers.access import paywall_text
            from services.subscriptions import check_access

            async with maker() as session:
                access = await check_access(session, UID)

            assert state.state is None
            assert callback.message.said == [paywall_text(access)]
    asyncio.run(scenario())


def test_demo_callback_is_open_without_access():
    from aiogram.types import CallbackQuery
    from middlewares.access import _is_open

    event = CallbackQuery.model_construct(data="demo:food")
    assert _is_open(event)


def test_start_demo_opens_the_state_for_an_eligible_user(monkeypatch):
    async def scenario():
        async with database(monkeypatch):
            import handlers.demo as handler

            state, callback = FakeState(), FakeCallback()
            await handler.start_demo(callback, state)

            assert state.state is not None
            assert handler.PROMPT in callback.message.said
            assert callback.answers[-1][1].get("show_alert") is not True
    asyncio.run(scenario())


def test_demo_button_is_added_to_the_plan_intro():
    from handlers.onboarding import plan_intro_keyboard

    with_demo = plan_intro_keyboard(demo=True)
    without = plan_intro_keyboard(demo=False)
    assert any(button.callback_data == "demo:food"
               for row in with_demo.inline_keyboard for button in row)
    assert not any(button.callback_data == "demo:food"
                   for row in without.inline_keyboard for button in row)
