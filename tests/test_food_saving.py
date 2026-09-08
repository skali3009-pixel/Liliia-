"""Кнопка «Сохранить» под карточкой еды.

Отдельный тест на неё появился после случая, который стоит помнить. Из
save_meal убрали параметр photo_file_id вместе с колонкой, а вызов в
обработчике остался. С этого дня ни одна еда из бота не сохранялась —
человек нажимал «Сохранить», ничего не происходило, и узнали мы об этом
от живого пользователя, а не от тестов.

Тесты на сервисы это не ловят: там всё в порядке. Ловится только тем, что
нажимает кнопку целиком, как человек.
"""

import asyncio
import contextlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db as db_module
from models import (ActivityLevelEnum, Base, GenderEnum, GoalEnum, Meal,
                    MealSourceEnum, User)
from services.food_vision import FoodAnalysis

USER_ID = 909

ANALYSIS = FoodAnalysis(
    name="Овсянка с бананом", weight_g=280, calories=390, protein_g=12,
    fat_g=9, carbs_g=64, fiber_g=7, confidence="high", comment="",
)


class FakeState:
    """FSM: помнит то же, что настоящая, и умеет очищаться."""

    def __init__(self, data: dict):
        self.data = dict(data)
        self.cleared = False

    async def get_data(self):
        return self.data

    async def set_data(self, data):
        self.data = data

    async def update_data(self, **values):
        self.data.update(values)

    async def clear(self):
        self.data = {}
        self.cleared = True


class FakeMessage:
    def __init__(self):
        self.said: list[str] = []
        self.markup_cleared = False

    async def answer(self, text, **kwargs):
        self.said.append(text)
        return self

    async def edit_reply_markup(self, **kwargs):
        self.markup_cleared = True


class FakeCallback:
    def __init__(self, user_id: int = USER_ID):
        self.from_user = type("U", (), {"id": user_id})()
        self.message = FakeMessage()
        self.answers: list[str] = []

    async def answer(self, text="", **kwargs):
        self.answers.append(text)


@contextlib.asynccontextmanager
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def get_session():
        async with maker() as session:
            yield session

    import handlers.food as food_module

    original_handler, original_db = food_module.get_session, db_module.get_session
    food_module.get_session = get_session
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
        food_module.get_session = original_handler
        db_module.get_session = original_db
        await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


@pytest.mark.parametrize("state_data,expected_source", [
    ({"analysis": ANALYSIS.to_dict(), "photo_file_id": "AgACAgIAAx0"},
     MealSourceEnum.PHOTO),
    ({"analysis": ANALYSIS.to_dict()}, MealSourceEnum.TEXT),
])
def test_pressing_save_actually_writes_the_meal(state_data, expected_source):
    """Главная проверка: человек нажал — еда в дневнике."""
    async def scenario():
        from handlers.food import save_food

        async with database() as maker:
            callback = FakeCallback()
            state = FakeState(state_data)

            await save_food(callback, state)

            async with maker() as session:
                meals = (await session.execute(select(Meal))).scalars().all()

            assert len(meals) == 1, "еда не сохранилась"
            assert meals[0].name == ANALYSIS.name
            assert meals[0].calories == ANALYSIS.calories
            assert meals[0].source == expected_source
            # Подтверждение человек читает в сообщении, а не во всплывашке.
            assert "Записал" in " ".join(callback.message.said)
            assert state.cleared, "карточка осталась висеть после сохранения"
    run(scenario)


def test_a_card_from_a_previous_version_explains_itself():
    """Раньше такая карточка просто молчала.

    Состояние жило в памяти, бот обновлялся сам раз в полчаса — и нажатие
    «Сохранить» после обновления не находило обработчика. Кнопка крутилась,
    пока Telegram не сдавался. Теперь состояние в базе, но старые карточки
    ещё встретятся, и они обязаны объяснить себя словами.
    """
    async def scenario():
        from handlers.food import save_food

        async with database() as maker:
            callback = FakeCallback()
            await save_food(callback, FakeState({}))

            async with maker() as session:
                assert (await session.execute(select(Meal))).first() is None
            assert "Пришли фото ещё раз" in " ".join(callback.message.said)
    run(scenario)


def test_the_button_stops_spinning_before_the_slow_part():
    """Пока считаются итоги дня и игровой пересчёт, кнопка не должна крутиться.

    Telegram ждёт ответа десять секунд. Не дождавшись, он перестаёт
    показывать нажатие — и снаружи это выглядит как «нажала, и ничего».
    """
    async def scenario():
        from handlers.food import save_food

        async with database():
            callback = FakeCallback()
            await save_food(callback, FakeState({"analysis": ANALYSIS.to_dict()}))
            assert callback.answers, "Telegram не получил ответа вовсе"
            assert callback.answers[0] == "Записываю…"
    run(scenario)


def test_pressing_save_twice_in_a_row_does_not_write_the_meal_twice():
    """Второе нажатие, пока считается первое, — обычное человеческое дело.

    Кнопка остаётся на месте всё время, пока идут итоги дня и игровой
    пересчёт. Нажатия проверяются именно одновременными: по очереди они и
    так безопасны, потому что карточка к тому времени уже забыта, — и
    тест, написанный по очереди, ничего бы не доказал.
    """
    async def scenario():
        from handlers.food import save_food

        async with database() as maker:
            state = FakeState({"analysis": ANALYSIS.to_dict()})
            await asyncio.gather(
                save_food(FakeCallback(), state),
                save_food(FakeCallback(), state),
            )

            async with maker() as session:
                meals = (await session.execute(select(Meal))).scalars().all()
            assert len(meals) == 1, "блюдо записалось дважды"
    run(scenario)


def test_a_stranger_without_a_profile_is_sent_to_start():
    async def scenario():
        from handlers.food import save_food

        async with database() as maker:
            callback = FakeCallback(user_id=12345)
            await save_food(callback, FakeState({"analysis": ANALYSIS.to_dict()}))

            async with maker() as session:
                assert (await session.execute(select(Meal))).first() is None
            assert "профиль" in " ".join(callback.message.said)
    run(scenario)


def test_the_answer_shows_what_is_left_for_today():
    """После сохранения человек должен видеть свой день, а не «ок»."""
    async def scenario():
        from handlers.food import save_food

        async with database():
            callback = FakeCallback()
            await save_food(callback, FakeState({"analysis": ANALYSIS.to_dict()}))
            summary = " ".join(callback.message.said)
            assert ANALYSIS.name in summary
            assert "390" in summary or "1600" in summary
            assert callback.message.markup_cleared, "кнопки под карточкой остались"
    run(scenario)


def test_no_handler_calls_a_service_with_an_argument_it_does_not_take():
    """Проверка того самого класса ошибок, а не одного его случая.

    Параметр убрали из функции, а вызов остался — и целая кнопка перестала
    работать. Тесты сервисов такое не видят: там всё в порядке.
    """
    import ast
    import importlib
    import inspect
    import pathlib as pl

    signatures = {}
    for name in ("services.meals", "services.subscriptions", "services.usage",
                 "services.cube", "services.checkins", "services.gamification",
                 "services.water", "services.weekly", "services.metrics",
                 "services.alerts", "services.menu", "services.dish_picker",
                 "services.food_vision", "services.reminders", "services.export"):
        module = importlib.import_module(name)
        for attribute, value in vars(module).items():
            if inspect.isfunction(value) and value.__module__ == name:
                signatures[attribute] = inspect.signature(value)

    problems = []
    files = (list(pl.Path("handlers").glob("*.py"))
             + list(pl.Path("webapp").glob("*.py"))
             + [pl.Path("scheduler.py"), pl.Path("bot.py")])
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            signature = signatures.get(node.func.id)
            if signature is None:
                continue
            if any(p.kind is inspect.Parameter.VAR_KEYWORD
                   for p in signature.parameters.values()):
                continue
            for keyword in node.keywords:
                if keyword.arg and keyword.arg not in signature.parameters:
                    problems.append(
                        f"{path}:{node.lineno} — {node.func.id}() не принимает "
                        f"«{keyword.arg}»")

    assert not problems, "\n".join(problems)
