"""«Мой ход» и гепард в чате.

Смысл этих проверок — не текст, а то, что чат и приложение думают одним
кодом. Разъехавшиеся правила проявляются не ошибкой, а тихим расхождением:
на экране одно, в чате другое, и найти это можно только глазами.
"""

import asyncio
import contextlib
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db as db_module
from models import (ActivityLevelEnum, Base, GenderEnum, GoalEnum, User)
from services import context, turn as turn_service

USER_ID = 707
ROOT = Path(__file__).resolve().parent.parent


@contextlib.asynccontextmanager
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def get_session():
        async with maker() as session:
            yield session

    import handlers.turn as turn_module

    original_handler, original_db = turn_module.get_session, db_module.get_session
    turn_module.get_session = get_session
    db_module.get_session = get_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(
            id=USER_ID, full_name="Лилия", gender=GenderEnum.FEMALE, age=30,
            height_cm=165, current_weight_kg=60, goal=GoalEnum.LOSE_WEIGHT,
            activity_level=ActivityLevelEnum.MODERATE, onboarding_completed=True,
            daily_calories=1600, daily_protein_g=120, daily_fat_g=48,
            daily_carbs_g=160, daily_fiber_g=22, daily_water_ml=2100,
            timezone="Europe/Moscow"))
        await session.commit()
    try:
        yield maker
    finally:
        turn_module.get_session = original_handler
        db_module.get_session = original_db
        await engine.dispose()


class FakeState:
    def __init__(self):
        self.cleared = False

    async def clear(self):
        self.cleared = True


class FakeMessage:
    def __init__(self, user_id: int = USER_ID):
        self.from_user = type("U", (), {"id": user_id})()
        self.said: list[str] = []
        self.markups: list = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self


def run(scenario):
    asyncio.run(scenario())


# --- Кнопка в чате ---------------------------------------------------------

def test_pressing_the_button_answers_with_the_cheetah_and_a_move():
    async def scenario():
        from handlers.turn import show_turn

        async with database():
            message, state = FakeMessage(), FakeState()
            await show_turn(message, state)

            assert len(message.said) == 1
            text = message.said[0]
            # Гепард отзывается — это первая строка.
            assert text.splitlines()[0].strip()
            # И цифры дня, ради которых человек и нажимает.
            assert "ккал" in text and "Вода" in text
    run(scenario)


def test_the_button_drops_an_unfinished_card():
    """Нажатая посреди добавления еды, кнопка меню иначе уедет в распознавание."""
    async def scenario():
        from handlers.turn import show_turn

        async with database():
            state = FakeState()
            await show_turn(FakeMessage(), state)
            assert state.cleared
    run(scenario)


def test_a_stranger_is_sent_to_the_questionnaire_not_to_a_crash():
    async def scenario():
        from handlers.turn import show_turn

        async with database():
            message = FakeMessage(user_id=12345)
            await show_turn(message, FakeState())
            assert "/start" in message.said[0]
    run(scenario)


def test_the_button_is_in_the_menu_and_the_menu_comes_back():
    from keyboards.main_menu import MENU_TURN, main_menu_keyboard

    buttons = [b.text for row in main_menu_keyboard().keyboard for b in row]
    assert buttons[0] == MENU_TURN, "«Мой ход» стоит первым: это вопрос «и что теперь?»"


# --- Куда ведёт подсказка --------------------------------------------------

def _all_targets() -> set[str]:
    """Все цели, которые вообще умеет выдавать подсказка."""
    targets = set()
    for hour in range(24):
        ctx = context.DayContext(
            hour=hour, calories=100, calories_target=2000, protein_g=5,
            protein_target=120, fiber_g=1, fiber_target=25, water_ml=0,
            water_target=2000, meals_logged=0, days_since_measure=30,
            preps_expiring=("Курица",), energy=1, stress="high",
            steps=0, steps_goal=8000, steps_logged=False,
        )
        targets |= {action.target for action in context._candidates(ctx)}
        rested = context.DayContext(hour=hour, energy=5, stress="low",
                                    meals_logged=1, calories_target=2000,
                                    steps=3000, steps_goal=8000, steps_logged=True)
        targets |= {action.target for action in context._candidates(rested)}
    return targets


# Что делается только на экране: отметить самочувствие в чате нечем. Для
# такого показывается кнопка «открыть приложение».
APP_ONLY = {"checkin"}


def test_every_suggestion_knows_where_it_leads_in_the_chat():
    """Новая подсказка без этой проверки молча окажется без выхода в чате."""
    unknown = _all_targets() - set(turn_service.CHAT_BUTTON) - APP_ONLY
    assert not unknown, f"подсказка ведёт в никуда: {unknown}"


def test_chat_hint_names_a_button_that_really_exists():
    from keyboards.main_menu import main_menu_keyboard

    buttons = {b.text for row in main_menu_keyboard().keyboard for b in row}
    assert set(turn_service.CHAT_BUTTON.values()) <= buttons


def test_app_only_suggestions_get_no_chat_hint():
    action = context.Action("checkin", "Состояние", "Как ты сегодня?",
                            "Отметить", "checkin")
    assert turn_service.chat_hint(action) is None
    assert turn_service.chat_hint(None) is None


# --- Один мозг на чат и приложение -----------------------------------------

def test_the_app_does_not_assemble_the_turn_on_its_own():
    """Скопированная сборка разъезжается тихо — поэтому её быть не должно."""
    api = (ROOT / "webapp" / "api.py").read_text(encoding="utf-8")
    assert "cheetah_mood(" not in api, "гепард снова собирается в двух местах"
    assert "DayContext(" not in api, "срез дня снова собирается в двух местах"
    assert "turn_service." in api


def test_the_chat_and_the_app_answer_from_the_same_state():
    """Одни данные — одна реакция гепарда, кто бы ни спрашивал."""
    async def scenario():
        async with database() as maker:
            async with maker() as session:
                from services.checkins import today_state
                from services.gamification import sync_today

                user = await session.get(User, USER_ID)
                turn = await turn_service.build(session, user)

                state = await today_state(session, USER_ID)
                game = await sync_today(session, user, meals_count=0, calories=0,
                                        fiber_g=0, water_ml=0, stress_marked=False)
                again = await turn_service.cheetah_for(
                    session, user, "Europe/Moscow", game=game, state=state, water=0)

            assert turn.cheetah.code == again.code
    run(scenario)


# --- Текст -----------------------------------------------------------------

def _turn(action, **over):
    from utils.cheetah import Mood

    fields = dict(cheetah=Mood("idle", "🐆", "Гепард дремлет."), action=action,
                  calories=400, calories_target=1600, water_ml=500,
                  water_target=2100, quests_done=2, quests_total=7,
                  level=3, streak=4)
    fields.update(over)
    return turn_service.Turn(**fields)


def test_the_message_names_the_button_to_press():
    action = context.Action("water", "Вода", "До нормы воды осталось 1600 мл. Стакан?",
                            "+250 мл", "water")
    text = turn_service.render(_turn(action))
    assert "Твой ход" in text and "Стакан?" in text
    assert "💧 Вода" in text


def test_nothing_urgent_is_said_plainly_instead_of_inventing_a_task():
    text = turn_service.render(_turn(None, hour=14, quests_done=2))
    assert "ничего срочного" in text.lower()
    assert "Твой ход" not in text


def test_the_night_is_not_called_a_day_well_spent():
    """«Всё идёт как надо» в одиннадцать вечера человеку с незакрытым днём —
    неправда, а неправда в мелочи бьёт по доверию ко всему остальному."""
    night = turn_service.render(_turn(None, hour=23, quests_done=1, quests_total=7))
    assert "ночь" in night.lower() and "как надо" not in night.lower()

    done = turn_service.render(_turn(None, hour=14, quests_done=7, quests_total=7))
    assert "закрыто" in done.lower()


def test_the_message_skips_numbers_that_are_not_set():
    text = turn_service.render(_turn(None, calories_target=None, water_target=None,
                                     quests_total=0, streak=0))
    assert "ккал" not in text and "Вода" not in text and "Задания" not in text
    assert "Уровень 3" in text


def test_pressing_twice_does_not_celebrate_forever():
    """Награда выдаётся один раз, иначе гепард будет ликовать до вечера."""
    async def scenario():
        from services.food_vision import FoodAnalysis
        from services.meals import save_meal
        from models import MealSourceEnum, MealTypeEnum

        async with database() as maker:
            async with maker() as session:
                await save_meal(session, user_id=USER_ID, analysis=FoodAnalysis(
                    name="Овсянка", weight_g=280, calories=390, protein_g=12,
                    fat_g=9, carbs_g=64, fiber_g=7, confidence="high", comment=""),
                    source=MealSourceEnum.PHOTO, meal_type=MealTypeEnum.BREAKFAST)
                user = await session.get(User, USER_ID)

                first = await turn_service.build(session, user)
                second = await turn_service.build(session, user)

            assert first.cheetah.code == "celebration"
            assert second.cheetah.code != "celebration"
    run(scenario)
