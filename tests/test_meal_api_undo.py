"""Приложение: запись из подбора, повтор нажатия, отмена — настоящими запросами."""

import asyncio
import pathlib
import re

from sqlalchemy import select

from models import MarketingEvent, Meal
from services import analytics
from tests.test_webapp_api import USER_ID, call, maker_holder, webapp_client

OFFER = {"name": "Гречка с курицей", "weight_g": 200, "calories": 280,
         "protein_g": 21, "fat_g": 7, "carbs_g": 32, "fiber_g": 3}


def run(scenario):
    asyncio.run(scenario())


async def count(model, **where):
    async with maker_holder["maker"]() as session:
        stmt = select(model)
        for key, value in where.items():
            stmt = stmt.where(getattr(model, key) == value)
        return len((await session.execute(stmt)).scalars().all())


async def event_total(event: str) -> int:
    async with maker_holder["maker"]() as session:
        rows = (await session.execute(
            select(MarketingEvent).where(MarketingEvent.event == event))).scalars().all()
        return sum(row.count for row in rows)


def test_saved_meal_comes_back_whole_so_it_can_be_undone():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/meals",
                                  json_body={**OFFER, "from_offer": True})
            assert response.status == 200
            data = await response.json()
            meal = data["meal"]
            assert meal["id"] and meal["name"] == OFFER["name"]
            assert meal["weight_g"] == 200 and meal["calories"] == 280
            assert await event_total(analytics.MEAL_FROM_OFFER) == 1

            # «Отменить» из плашки — тот же DELETE, что в дневнике.
            response = await call(client, "DELETE", f"/api/meals/{meal['id']}")
            assert response.status == 200
            assert await count(Meal, name=OFFER["name"]) == 0
            assert await event_total(analytics.MEAL_UNDONE) == 1

            today = await (await call(client, "GET", "/api/today")).json()
            assert all(m["name"] != OFFER["name"] for m in today["meals"])
    run(scenario)


def test_the_same_press_sent_twice_writes_once():
    """Двойной тап или переотправка после плохой сети — одна запись."""
    async def scenario():
        async with webapp_client() as (client, _):
            body = {**OFFER, "request_id": "tap-1"}
            first, second = await asyncio.gather(
                call(client, "POST", "/api/meals", json_body=body),
                call(client, "POST", "/api/meals", json_body=body),
            )
            statuses = sorted([first.status, second.status])
            assert statuses in ([200, 200], [200, 409]), statuses
            assert await count(Meal, name=OFFER["name"]) == 1

            # Уже записанный ключ возвращает ту же запись, а не новую.
            again = await call(client, "POST", "/api/meals", json_body=body)
            data = await again.json()
            assert data.get("repeat") is True
            assert await count(Meal, name=OFFER["name"]) == 1

            # Другое нажатие — другой ключ — законная вторая запись.
            await call(client, "POST", "/api/meals",
                       json_body={**OFFER, "request_id": "tap-2"})
            assert await count(Meal, name=OFFER["name"]) == 2
    run(scenario)


def test_the_key_of_one_person_does_not_touch_another():
    async def scenario():
        from tests.test_webapp_api import OTHER_ID

        async with webapp_client() as (client, _):
            body = {**OFFER, "request_id": "same"}
            await call(client, "POST", "/api/meals", json_body=body)
            response = await call(client, "POST", "/api/meals", json_body=body,
                                  user_id=OTHER_ID)
            assert (await response.json()).get("repeat") is not True
            assert await count(Meal, user_id=OTHER_ID) == 1
    run(scenario)


def test_a_chat_record_is_undone_from_the_app_and_back():
    """Чат ↔ приложение: одна база, одна запись, одна отмена."""
    async def scenario():
        from models import MealSourceEnum, MealTypeEnum
        from services.food_vision import FoodAnalysis
        from services.meals import delete_meal, save_meal

        async with webapp_client() as (client, _):
            async with maker_holder["maker"]() as session:
                meal = await save_meal(
                    session, user_id=USER_ID,
                    analysis=FoodAnalysis(name="Из чата", weight_g=100, calories=150,
                                          protein_g=5, fat_g=5, carbs_g=20, fiber_g=1,
                                          confidence="medium", comment=""),
                    source=MealSourceEnum.TEXT, meal_type=MealTypeEnum.LUNCH,
                    from_offer=True)
            today = await (await call(client, "GET", "/api/today")).json()
            assert any(m["id"] == meal.id for m in today["meals"])

            # Правка веса в приложении — та же дорога, что «Исправить вес» в чате.
            response = await call(client, "PATCH", f"/api/meals/{meal.id}",
                                  json_body={"weight_g": 50})
            assert (await response.json())["calories"] == 75

            await call(client, "DELETE", f"/api/meals/{meal.id}")
            # А из приложения записали — в чате отменить уже нечего.
            async with maker_holder["maker"]() as session:
                assert await session.get(Meal, meal.id) is None
                response = await call(client, "POST", "/api/meals", json_body=OFFER)
                made = (await response.json())["meal"]
                row = await session.get(Meal, made["id"])
                await delete_meal(session, row)
            assert await count(Meal, name=OFFER["name"]) == 0
    run(scenario)


APP = pathlib.Path("webapp/static/app.js").read_text()
PAGE = pathlib.Path("webapp/static/index.html").read_text()


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start:APP.index("\n}", start)]


def test_every_way_to_write_food_in_the_app_goes_through_one_door():
    """Подбор, рецепт, кубик и «ешь как обычно» пишут через recordMeal.

    Второй путь записи — это второй набор правил: у него не было бы ни
    «Отменить», ни защиты от двойного тапа. Поэтому POST на /api/meals в
    приложении ровно один.
    """
    assert len(re.findall(r"api\('/api/meals',", APP)) == 1
    assert "api('/api/meals'" in _function("recordMeal")
    assert "recordMeal(" in _function("eatOffer")
    assert "recordMeal(" in _function("eatCube")
    # Подбор и кубик спрашивают порцию, «ешь как обычно» — нет: вес своё.
    assert "{ ask: false" not in _function("eatOffer")
    assert "{ ask: false" not in _function("eatCube")


def test_the_portion_question_calls_the_estimate_an_estimate():
    body = _function("askPortion")
    assert "примерная оценка" in body
    assert "≈" in body
    assert "Свой вес" in body


def test_after_saving_there_is_undo_and_fix():
    body = _function("savedToast")
    assert "Отменить" in body and "Исправить" in body
    assert "method: 'DELETE'" in body
    assert "editWeight(" in body


def test_the_offer_buttons_do_not_guess_who_is_eating():
    for text in (APP, PAGE):
        assert "Съела это" not in text
        assert ">Съел<" not in text
