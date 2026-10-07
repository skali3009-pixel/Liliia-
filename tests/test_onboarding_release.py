"""Registration, draft review, restart recovery, and the first useful action."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import Chat, Message as TelegramMessage, User as TelegramUser
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import config
from handlers import onboarding as O
from handlers.legal import LEGAL_VERSION
from keyboards.main_menu import MENU_TEXTS
from migrations import apply_column_additions
from models import User
from services import fsm_storage
from states.onboarding import OnboardingStates
from tests.test_onboarding_flow import (
    ОНА as USER_ID, Человек as Person, ФейковаяКнопка as Button,
    ФейковоеСообщение as Message, контекст as context, стенд as database,
)


async def draft(chat, state, interest="food"):
    await O.begin_onboarding(Message(chat), state, USER_ID)
    await O.process_interest(Button(chat, f"onb_interest:{interest}"), state)
    await O.process_name(Message(chat, "Тимур", Person()), state)
    await O.process_gender(Button(chat, "onb_gender:male"), state)
    await O.process_age(Message(chat, "30", Person()), state)
    await O.process_height(Message(chat, "180", Person()), state)
    await O.process_current_weight(Message(chat, "80", Person()), state)
    await O.process_activity(Button(chat, "onb_activity:moderate"), state)
    await O.process_goal(Button(chat, "onb_goal:maintain"), state)
    await O.process_diet_type(Button(chat, "onb_diet:regular"), state)
    # Diet choice must not treat an absent allergy answer as "none".
    assert await state.get_state() == OnboardingStates.allergies.state
    await O.process_allergies(Message(chat, "орехи", Person()), state)
    assert await state.get_state() == OnboardingStates.summary.state


@pytest.mark.parametrize("interest, expected", [("food", "приёма пищи"), ("move", "тренировки"), ("both", "выбери одно")])
def test_confirmation_saves_the_person_then_offers_the_selected_action(monkeypatch, interest, expected):
    async def scenario():
        async with database(monkeypatch) as maker:
            chat, state = [], context()
            await draft(chat, state, interest)
            async with maker() as session:
                user = await session.get(User, USER_ID)
                assert not user.onboarding_completed
                assert user.current_weight_kg is None and user.allergies is None
            assert "Проверь ответы" in chat[-1][0]
            await O.confirm_summary(Button(chat, "onb:confirm"), state)
            async with maker() as session:
                user = await session.get(User, USER_ID)
                assert user.onboarding_completed and user.daily_calories > 0
                assert (user.full_name, user.onboarding_interest, user.allergies) == ("Тимур", interest, "орехи")
            assert expected in chat[-1][0]
            assert await state.get_state() is None
            callbacks = [data for _, data in chat[-1][1]]
            if interest == "food":
                assert callbacks == [O.CB_FIRST_MEAL]
            elif interest == "move":
                assert O.CB_FIRST_MEAL not in callbacks
    asyncio.run(scenario())


@pytest.mark.parametrize("field, process, value, expected", [
    ("profile_name", "process_name", "Алекс", "Алекс"),
    ("age", "process_age", "33", 33),
    ("height_cm", "process_height", "175", 175),
    ("current_weight_kg", "process_current_weight", "79.5", 79.5),
    ("allergies", "process_allergies", "молоко", "молоко"),
])
def test_editing_a_field_returns_to_review_without_saving(monkeypatch, field, process, value, expected):
    async def scenario():
        async with database(monkeypatch) as maker:
            chat, state = [], context()
            await draft(chat, state)
            await O.edit_summary(Button(chat, f"onb_edit:{field}"), state)
            await getattr(O, process)(Message(chat, value, Person()), state)
            assert await state.get_state() == OnboardingStates.summary.state
            assert (await state.get_data())[field] == expected
            assert "Проверь ответы" in chat[-1][0]
            async with maker() as session:
                assert not (await session.get(User, USER_ID)).onboarding_completed
    asyncio.run(scenario())


@pytest.mark.parametrize("field, process, value, expected", [
    ("interest", "process_interest", "onb_interest:move", "move"),
    ("gender", "process_gender", "onb_gender:female", "female"),
    ("activity_level", "process_activity", "onb_activity:light", "light"),
    ("goal", "process_goal", "onb_goal:lose_weight", "lose_weight"),
    ("diet_type", "process_diet_type", "onb_diet:vegan", "vegan"),
])
def test_editing_a_choice_returns_to_review(monkeypatch, field, process, value, expected):
    async def scenario():
        async with database(monkeypatch):
            chat, state = [], context()
            await draft(chat, state)
            await O.edit_summary(Button(chat, f"onb_edit:{field}"), state)
            await getattr(O, process)(Button(chat, value), state)
            assert await state.get_state() == OnboardingStates.summary.state
            assert (await state.get_data())[field] == expected
    asyncio.run(scenario())


def test_a_draft_and_its_edits_survive_a_storage_restart(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            monkeypatch.setattr(fsm_storage, "get_session", O.get_session)
            async with maker() as session:
                user = await session.get(User, USER_ID)
                user.legal_version = LEGAL_VERSION
                user.legal_accepted_at = datetime.now(timezone.utc)
                await session.commit()
            key = StorageKey(bot_id=1, chat_id=USER_ID, user_id=USER_ID)
            state = FSMContext(fsm_storage.DatabaseStorage(), key)
            chat = []
            await draft(chat, state)
            await O.edit_summary(Button(chat, "onb_edit:height_cm"), state)
            restarted = FSMContext(fsm_storage.DatabaseStorage(), key)
            assert await restarted.get_state() == OnboardingStates.height.state
            await O.process_height(Message(chat, "182", Person()), restarted)
            assert "Рост: 182 см" in chat[-1][0]
            await O.cmd_start(Message(chat, "/start", Person()), restarted, SimpleNamespace(args=None))
            assert "Имя: Тимур" in chat[-1][0]
            assert (await restarted.get_data())["allergies"] == "орехи"
    asyncio.run(scenario())


def test_a_saved_name_is_not_overwritten_by_another_start(monkeypatch):
    async def scenario():
        import datetime
        async with database(monkeypatch) as maker:
            chat, state = [], context()
            await draft(chat, state)
            await O.confirm_summary(Button(chat, "onb:confirm"), state)
            async with maker() as session:
                user = await session.get(User, USER_ID)
                user.legal_version = LEGAL_VERSION
                user.legal_accepted_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
            await O.cmd_start(Message(chat, "/start", Person(full_name="Имя Telegram")), state, SimpleNamespace(args=None))
            async with maker() as session:
                user = await session.get(User, USER_ID)
                assert user.full_name == "Тимур" and user.onboarding_interest == "food"
    asyncio.run(scenario())


@pytest.mark.parametrize("current", [OnboardingStates.name, OnboardingStates.allergies])
def test_real_router_does_not_record_menu_buttons_or_commands_as_answers(monkeypatch, current):
    async def scenario():
        async with database(monkeypatch):
            state = context()
            await state.set_state(current)
            await state.update_data(profile_name="Тимур", allergies="орехи")
            before = await state.get_data()
            for value in list(MENU_TEXTS) + ["/start", "/tariffs", "/documents"]:
                if value == "/start":
                    # /start is a separate registered route, and deliberately resumes.
                    continue
                message = TelegramMessage(message_id=1, date=datetime.now(timezone.utc),
                    chat=Chat(id=USER_ID, type="private"), text=value,
                    from_user=TelegramUser(id=USER_ID, is_bot=False, first_name="Тимур"))
                await O.router.propagate_event("message", message, state=state,
                    raw_state=current.state, bot=SimpleNamespace())
                assert await state.get_data() == before
    asyncio.run(scenario())


def test_old_drafts_get_a_review_and_keep_their_answers(monkeypatch):
    async def scenario():
        async with database(monkeypatch):
            chat, state = [], context()
            await state.update_data(gender="female", age=31, height_cm=168,
                current_weight_kg=63.5, activity_level="moderate", goal="maintain", diet_type="regular")
            await state.set_state(OnboardingStates.allergies)
            await O.process_allergies(Message(chat, "нет", Person()), state)
            assert await state.get_state() == OnboardingStates.summary.state
            data = await state.get_data()
            assert data["age"] == 31 and data["profile_name"] == "Лилия Скалий"
            assert data["allergies"] is None and data["interest"] == "both"
    asyncio.run(scenario())


def test_user_text_cannot_inject_html_into_the_review(monkeypatch):
    async def scenario():
        async with database(monkeypatch):
            chat, state = [], context()
            await draft(chat, state)
            await O.edit_summary(Button(chat, "onb_edit:profile_name"), state)
            await O.process_name(Message(chat, "<b>Алекс</b>", Person()), state)
            assert "&lt;b&gt;Алекс&lt;/b&gt;" in chat[-1][0]
            assert "<b>Алекс</b>" not in chat[-1][0]
    asyncio.run(scenario())


def test_migration_adds_interest_without_changing_existing_profiles():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE users (id BIGINT PRIMARY KEY, full_name VARCHAR(255), onboarding_completed BOOLEAN)"))
            await conn.execute(text("INSERT INTO users VALUES (1, 'Лилия', TRUE)"))
            await apply_column_additions(conn)
            await apply_column_additions(conn)
            row = (await conn.execute(text("SELECT full_name, onboarding_completed, onboarding_interest FROM users"))).one()
            assert tuple(row) == ("Лилия", 1, None)
        await engine.dispose()
    asyncio.run(scenario())


def test_review_has_two_actions_and_opens_an_edit_selector(monkeypatch):
    async def scenario():
        async with database(monkeypatch):
            chat, state = [], context()
            await draft(chat, state)
            assert [data for _, data in chat[-1][1]] == ["onb:confirm", "onb:edit_fields"]
            await O.choose_edit_field(Button(chat, "onb:edit_fields"))
            assert len(chat[-1][1]) == 11
            await O.review_again(Button(chat, "onb:review"), state)
            assert "Проверь ответы" in chat[-1][0]
    asyncio.run(scenario())


def test_a_review_reminder_does_not_request_the_questions_again(monkeypatch):
    from models import FsmState
    from services import unfinished
    async def scenario():
        async with database(monkeypatch) as maker:
            async with maker() as session:
                session.add(FsmState(key=fsm_storage._key(StorageKey(bot_id=1, chat_id=USER_ID, user_id=USER_ID)),
                    state=OnboardingStates.summary.state, data="{}"))
                await session.commit()
                stopped = await unfinished._stopped_at(session, [USER_ID])
                text = unfinished.render(stopped[USER_ID], O.ВСЕГО_ШАГОВ)
                assert "Проверь сводку" in text and "вопросе" not in text
    asyncio.run(scenario())


def test_two_confirmations_cannot_change_a_completed_profile(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            chat, state = [], context()
            await draft(chat, state)
            data = await state.get_data()
            await O.confirm_summary(Button(chat, "onb:confirm"), state)
            # A stale draft must not overwrite the completed profile.
            await state.set_data({**data, "profile_name": "Старый черновик", "current_weight_kg": 50})
            await O.confirm_summary(Button(chat, "onb:confirm"), state)
            async with maker() as session:
                user = await session.get(User, USER_ID)
                assert user.full_name == "Тимур" and user.current_weight_kg == 80
    asyncio.run(scenario())


def test_confirmation_is_really_routed_and_a_repeat_only_answers(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            chat, state = [], context()
            await draft(chat, state)
            press = Button(chat, "onb:confirm")
            await O.router.propagate_event("callback_query", press, state=state,
                raw_state=await state.get_state(), bot=SimpleNamespace())
            async with maker() as session:
                assert (await session.get(User, USER_ID)).onboarding_completed
            count = len(chat)
            await O.router.propagate_event("callback_query", press, state=state,
                raw_state=await state.get_state(), bot=SimpleNamespace())
            assert len(chat) == count and await state.get_state() is None
    asyncio.run(scenario())


@pytest.mark.parametrize("paywall", [False, True])
def test_operations_report_does_not_suggest_enabling_disabled_sales(monkeypatch, paywall):
    from services.status import _access_mode
    monkeypatch.setattr(config, "PAYWALL", paywall)
    monkeypatch.setattr(config, "STARS_PAYMENTS_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_IDS", {1})
    report = "\n".join(_access_mode())
    assert "/tariffs" in report and "set-paywall.sh on" not in report
