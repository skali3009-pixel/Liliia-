"""The public catalogue is inspectable and cannot start a purchase."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, User

import config
from handlers import access, tariffs
from keyboards.main_menu import MENU_TARIFFS, MENU_TEXTS, main_menu_keyboard
from services.tariffs import PLANS, catalogue, plan_text
from states.onboarding import OnboardingStates
from states.steps import StepStates
from webapp.server import create_app


def test_price_and_allowances_match_the_period():
    short, long = PLANS
    assert (short.days, short.price_rub, short.recognitions, short.dish_builds) == (30, 490, 120, 10)
    assert (long.days, long.price_rub, long.recognitions, long.dish_builds) == (90, 1290, 360, 30)
    assert long.saving_rub == short.price_rub * 3 - long.price_rub == 180
    assert catalogue()["sales_enabled"] is False
    for plan in PLANS:
        text = plan_text(plan)
        assert "пока не действуют" in text and "без оплаты" in text
    assert MENU_TARIFFS in MENU_TEXTS
    assert MENU_TARIFFS in {b.text for row in main_menu_keyboard().keyboard for b in row}


def test_public_price_page_and_json_open_without_telegram_or_paid_access(monkeypatch):
    monkeypatch.setattr(config, "PAYWALL", True)
    monkeypatch.setattr(config, "WEBAPP_URL", "https://aura.example")
    async def run():
        async with TestClient(TestServer(create_app())) as client:
            reply = await client.get("/tariffs.json")
            assert reply.status == 200
            assert await reply.json() == catalogue()
            page = await client.get("/tariffs")
            assert page.status == 200
            body = await page.text()
            assert body.count("<summary>") == 2
            assert "490 ₽" in body and "1 290 ₽" in body
            for slug in ("offer", "privacy", "consent", "marketing"):
                assert f"/legal/{slug}" in body
            # Publishing prices must not bypass authentication for private data.
            assert (await client.get("/api/profile")).status == 401
    asyncio.run(run())


@pytest.mark.parametrize("previous,expected", [(None, None),
    (OnboardingStates.age, OnboardingStates.age.state), (StepStates.waiting_number, None)])
def test_menu_press_routes_and_preserves_only_the_questionnaire(previous, expected):
    async def run():
        state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))
        if previous: await state.set_state(previous)
        message = SimpleNamespace(text=MENU_TARIFFS, answer=AsyncMock())
        await tariffs.router.propagate_event(update_type="message", event=message,
            state=state, raw_state=await state.get_state(), bot=SimpleNamespace(id=1))
        assert await state.get_state() == expected
        message.answer.assert_awaited_once()
        markup = message.answer.call_args.kwargs["reply_markup"]
        assert {b.callback_data for row in markup.inline_keyboard for b in row} == {"tariff:30", "tariff:90"}
        assert all(b.url is None for row in markup.inline_keyboard for b in row)
    asyncio.run(run())


@pytest.mark.parametrize("plan_id", ["30", "90"])
def test_description_click_uses_the_same_catalogue_and_never_creates_an_invoice(plan_id):
    async def run():
        invoice = AsyncMock()
        callback = SimpleNamespace(data=f"tariff:{plan_id}", answer=AsyncMock(),
            message=SimpleNamespace(answer=AsyncMock()), bot=SimpleNamespace(create_invoice_link=invoice))
        await tariffs.show_plan(callback)
        text = callback.message.answer.call_args.args[0]
        assert text == plan_text(next(plan for plan in PLANS if plan.id == plan_id))
        invoice.assert_not_awaited()
    asyncio.run(run())


def test_stale_stars_button_and_checkout_cannot_charge_even_if_legacy_paywall_is_enabled(monkeypatch):
    monkeypatch.setattr(config, "PAYWALL", True)
    monkeypatch.setattr(config, "STARS_PAYMENTS_ENABLED", False)
    async def run():
        callback = SimpleNamespace(answer=AsyncMock(), message=SimpleNamespace(answer=AsyncMock()),
            bot=SimpleNamespace(create_invoice_link=AsyncMock()))
        await access.start_payment(callback)
        callback.bot.create_invoice_link.assert_not_awaited()
        assert "Тарифы" in callback.message.answer.call_args.args[0]
        query = SimpleNamespace(answer=AsyncMock())
        await access.approve_payment(query)
        assert query.answer.call_args.kwargs["ok"] is False
        message = SimpleNamespace(answer=AsyncMock())
        await access.show_subscription(message)
        assert "Тарифы" in message.answer.call_args.args[0]
    asyncio.run(run())


def test_price_navigation_is_available_before_payment_and_for_a_minor():
    from middlewares.access import _is_open as paid_open
    from middlewares.minor import _is_open as minor_open
    for text in (MENU_TARIFFS, "/tariffs", "/subscription"):
        event = Message(message_id=1, date=datetime.now(timezone.utc),
            chat=Chat(id=1, type="private"), from_user=User(id=1, is_bot=False, first_name="Test"), text=text)
        assert paid_open(event)
        assert minor_open(event, None)
