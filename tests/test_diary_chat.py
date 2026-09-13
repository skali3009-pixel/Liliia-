"""Дневник за сегодня в чате.

Записать еду из переписки было можно, а посмотреть записанное — нет: список
жил только в приложении. «Что я сегодня ела» — самый частый вопрос дня, и
ради него человека выгоняли на другой экран. Ошибочную запись оттуда же
нельзя было убрать.
"""

import asyncio
import contextlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db as db_module
from models import (ActivityLevelEnum, Base, GenderEnum, GoalEnum, Meal,
                    MealSourceEnum, MealTypeEnum, User)
from services.food_vision import FoodAnalysis
from services.meals import save_meal

USER = 1
OTHER = 2


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def get_session():
        async with maker() as session:
            yield session

    import handlers.diary as module

    original, original_db = module.get_session, db_module.get_session
    module.get_session = get_session
    db_module.get_session = get_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for user_id in (USER, OTHER):
            session.add(User(
                id=user_id, full_name="Лилия", gender=GenderEnum.FEMALE, age=30,
                height_cm=165, current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                activity_level=ActivityLevelEnum.MODERATE, onboarding_completed=True,
                daily_calories=1600, daily_protein_g=120, daily_fat_g=48,
                daily_carbs_g=160, daily_fiber_g=22, daily_water_ml=2100,
                timezone="Europe/Moscow"))
        await session.commit()
    try:
        yield maker
    finally:
        module.get_session = original
        db_module.get_session = original_db
        await engine.dispose()


async def eat(maker, user_id: int, name: str, kcal: float, meal_type):
    async with maker() as session:
        return await save_meal(session, user_id=user_id, analysis=FoodAnalysis(
            name=name, weight_g=300, calories=kcal, protein_g=20, fat_g=10,
            carbs_g=30, fiber_g=4, confidence="high", comment=""),
            source=MealSourceEnum.TEXT, meal_type=meal_type)


class FakeMessage:
    def __init__(self, user_id=USER):
        self.from_user = type("U", (), {"id": user_id})()
        self.said: list[str] = []
        self.edits: list[str] = []
        self.markups: list = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        self.markups.append(kwargs.get("reply_markup"))


class FakeCallback:
    def __init__(self, data, user_id=USER):
        self.data = data
        self.from_user = type("U", (), {"id": user_id})()
        self.message = FakeMessage(user_id)
        self.answers: list[str] = []

    async def answer(self, text="", **kwargs):
        self.answers.append(text)


def run(scenario):
    asyncio.run(scenario())


# --- Показать --------------------------------------------------------------

def test_the_day_shows_what_was_eaten_and_the_totals():
    async def scenario():
        from handlers.diary import show_day

        async with db() as maker:
            await eat(maker, USER, "Овсянка", 380, MealTypeEnum.BREAKFAST)
            await eat(maker, USER, "Куриная грудка", 520, MealTypeEnum.LUNCH)

            message = FakeMessage()
            await show_day(message)

            text = message.said[0]
            assert "Овсянка" in text and "Куриная грудка" in text
            assert "900" in text and "1600" in text
    run(scenario)


def test_an_empty_day_says_so_instead_of_showing_an_empty_list():
    async def scenario():
        from handlers.diary import show_day

        async with db():
            message = FakeMessage()
            await show_day(message)
            assert "пусто" in message.said[0]
            assert message.markups[0] is not None
    run(scenario)


def test_each_meal_gets_a_button_to_remove_it():
    async def scenario():
        from handlers.diary import show_day

        async with db() as maker:
            await eat(maker, USER, "Овсянка", 380, MealTypeEnum.BREAKFAST)

            message = FakeMessage()
            await show_day(message)
            markup = message.markups[0]
            buttons = [b for row in markup.inline_keyboard for b in row]
            assert len(buttons) == 1 and "Овсянка" in buttons[0].text
    run(scenario)


def test_a_very_long_day_does_not_turn_into_a_wall_of_buttons():
    async def scenario():
        from handlers.diary import MAX_ROWS, show_day

        async with db() as maker:
            for index in range(MAX_ROWS + 4):
                await eat(maker, USER, f"Блюдо {index}", 100, MealTypeEnum.SNACK)

            message = FakeMessage()
            await show_day(message)
            markup = message.markups[0]
            buttons = [b for row in markup.inline_keyboard for b in row]
            assert len(buttons) == MAX_ROWS
            assert "и ещё 4" in message.said[0]
    run(scenario)


# --- Удалить ---------------------------------------------------------------

def test_a_wrong_entry_is_removed_in_one_tap():
    async def scenario():
        from handlers.diary import CB_DROP, drop_meal

        async with db() as maker:
            meal = await eat(maker, USER, "Овсянка", 380, MealTypeEnum.BREAKFAST)
            await eat(maker, USER, "Суп", 200, MealTypeEnum.LUNCH)

            callback = FakeCallback(f"{CB_DROP}{meal.id}")
            await drop_meal(callback)

            async with maker() as session:
                left = (await session.execute(select(Meal))).scalars().all()
            assert [m.name for m in left] == ["Суп"]
            # Список сразу перерисовался, а не остался со старой строкой.
            assert "Овсянка" not in callback.message.edits[0]
    run(scenario)


def test_the_last_entry_removed_leaves_an_honest_empty_day():
    async def scenario():
        from handlers.diary import CB_DROP, drop_meal

        async with db() as maker:
            meal = await eat(maker, USER, "Овсянка", 380, MealTypeEnum.BREAKFAST)

            callback = FakeCallback(f"{CB_DROP}{meal.id}")
            await drop_meal(callback)
            assert "пусто" in callback.message.edits[0]
    run(scenario)


def test_someone_elses_meal_cannot_be_removed_even_knowing_its_number():
    async def scenario():
        from handlers.diary import CB_DROP, drop_meal

        async with db() as maker:
            meal = await eat(maker, OTHER, "Чужой обед", 700, MealTypeEnum.LUNCH)

            callback = FakeCallback(f"{CB_DROP}{meal.id}", user_id=USER)
            await drop_meal(callback)

            async with maker() as session:
                left = (await session.execute(select(Meal))).scalars().all()
            assert len(left) == 1, "чужая запись удалилась"
    run(scenario)


def test_a_broken_button_does_not_crash():
    async def scenario():
        from handlers.diary import CB_DROP, drop_meal

        async with db():
            callback = FakeCallback(f"{CB_DROP}не-число")
            await drop_meal(callback)
            assert callback.answers
    run(scenario)


def test_the_command_is_in_the_menu_and_the_food_screen_points_at_it():
    from pathlib import Path

    from services import commands

    assert "day" in {name for name, _ in commands.public()}
    food = (Path(__file__).resolve().parent.parent / "handlers" /
            "food.py").read_text(encoding="utf-8")
    assert "/day" in food
