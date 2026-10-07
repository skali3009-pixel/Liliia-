"""AURA — с 18 лет. Решение 27.09.

Согласие и оферта всегда говорили «старше 18», а анкета принимала от 10, и
17-летнему профилю считалась взрослая норма (запись экрана 26.09). Теперь:
новый человек младше 18 получает честный отказ в анкете; у заведённых
раньше данные остаются, а нормы, подбор и рассылки — выключаются.
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from models import User
from services import age as age_rules
from tests.test_webapp_api import USER_ID, call, maker_holder, webapp_client


def run(scenario):
    asyncio.run(scenario())


async def make_minor(age=17):
    async with maker_holder["maker"]() as session:
        user = await session.get(User, USER_ID)
        user.age = age
        await session.commit()


def test_the_questionnaire_refuses_under_18_and_remembers_why():
    async def scenario():
        from handlers.onboarding import process_age
        from tests.test_offer_is_not_meal import Message, State
        import handlers.onboarding as onboarding
        import db as db_module

        async with webapp_client():
            original = onboarding.get_session
            onboarding.get_session = db_module.get_session
            try:
                state = State({"gender": "male"})
                message = Message(USER_ID)
                message.text = "17"
                await process_age(message, state)
            finally:
                onboarding.get_session = original
            assert message.said[-1] == age_rules.REFUSAL
            assert state.cleared, "анкета продолжилась у 17-летнего"
            async with maker_holder["maker"]() as session:
                assert (await session.get(User, USER_ID)).age == 17
    run(scenario)


def test_adults_are_not_touched_by_the_rule():
    from services.profile import valid_age

    assert valid_age(18) and valid_age(45)
    assert not valid_age(17) and not valid_age(10)
    assert not age_rules.is_minor(User(age=18))
    assert not age_rules.is_minor(User(age=None))
    assert age_rules.is_minor(User(age=17))


def test_the_app_shows_nothing_personal_to_a_minor_but_keeps_their_data():
    async def scenario():
        async with webapp_client() as (client, _):
            await make_minor()
            today = await call(client, "GET", "/api/today")
            assert today.status == 403
            body = await today.json()
            assert body["minor"] is True and body["error"] == age_rules.NOTICE
            for path in ("/api/menu", "/api/workouts", "/api/progress"):
                assert (await call(client, "GET", path)).status == 403
            # Профиль (поправить возраст) и выгрузка — на месте.
            assert (await call(client, "GET", "/api/profile")).status == 200
            fixed = await call(client, "PATCH", "/api/profile", json_body={"age": 19})
            assert fixed.status == 200
            assert (await call(client, "GET", "/api/today")).status == 200
    run(scenario)


@pytest.mark.parametrize("text,passes", [
    ("🍽 Что съесть", False), ("/start", False), ("огурец", False),
    ("/export", True), ("/delete", True), ("/problem", True), ("/legal", True),
    ("⚙️ Профиль и доступ", True),
])
def test_the_chat_lets_a_minor_reach_only_their_data_and_support(text, passes):
    async def scenario():
        from aiogram.types import Chat, Message as TgMessage, User as TgUser
        from datetime import datetime
        from middlewares.minor import MinorMiddleware
        import middlewares.minor as minor_module
        import db as db_module

        async with webapp_client():
            await make_minor()
            original = minor_module.get_session
            minor_module.get_session = db_module.get_session
            answered = []

            async def answer(self, text, **kwargs):
                answered.append(text)
            original_answer = TgMessage.answer
            try:
                TgMessage.answer = answer
                event = TgMessage(message_id=1, date=datetime.now(),
                                  chat=Chat(id=USER_ID, type="private"),
                                  from_user=TgUser(id=USER_ID, is_bot=False, first_name="x"),
                                  text=text)
                called = []

                async def handler(event, data):
                    called.append(True)
                await MinorMiddleware()(handler, event,
                                        {"event_from_user": SimpleNamespace(id=USER_ID)})
            finally:
                minor_module.get_session = original
                TgMessage.answer = original_answer
            assert bool(called) is passes
            if not passes:
                assert answered == [age_rules.NOTICE]
    run(scenario)


def test_a_minor_editing_their_age_is_let_through():
    async def scenario():
        from middlewares.minor import _is_open

        assert _is_open(SimpleNamespace(), "ProfileStates:age")
        assert _is_open(SimpleNamespace(), "FeedbackStates:writing")
        assert not _is_open(SimpleNamespace(), "FoodStates:waiting_input")
    run(scenario)


def test_the_bot_does_not_write_first_to_a_minor():
    """Рассылки (подсказки, итоги, письма вернувшимся) минуют младше 18."""
    async def scenario():
        async with webapp_client():
            await make_minor()
            async with maker_holder["maker"]() as session:
                ids = (await session.execute(select(User.id).where(
                    User.onboarding_completed.is_(True),
                    age_rules.adult_clause()))).scalars().all()
            assert USER_ID not in ids and ids
    run(scenario)


def test_every_mailing_query_carries_the_age_rule():
    import pathlib

    # Каждый запрос, который отбирает людей для рассылки, — а не хотя бы
    # один в файле: пропущенный второй запрос молча вернул бы рассылку.
    for name in ("comeback", "notifications", "weekly", "step_results", "unfinished"):
        source = pathlib.Path(f"services/{name}.py").read_text(encoding="utf-8")
        selections = source.count("User.reminders_enabled.is_(True)")
        if name == "unfinished":
            selections = 1   # отбор людей там один, второй — только пояса
        assert source.count("adult_clause()") >= selections, name


def test_the_chat_profile_of_a_minor_has_no_norms():
    from handlers.profile import profile_text

    minor = User(age=17, daily_calories=2990, reminders_enabled=True)
    text = profile_text(minor)
    assert age_rules.NOTICE in text
    assert "2990" not in text
