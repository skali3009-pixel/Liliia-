"""Проверка API мини-приложения: настоящие HTTP-запросы к настоящей базе."""

import asyncio
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
import db as db_module
from models import Base, DietTypeEnum, GenderEnum, GoalEnum, MealSourceEnum, MealTypeEnum, User
from services.food_vision import FoodAnalysis
from services.meals import save_meal

USER_ID = 4242
OTHER_ID = 777
TOKEN = config.BOT_TOKEN


def init_data(user_id: int = USER_ID) -> str:
    fields = {
        "user": json.dumps({"id": user_id, "first_name": "Лилия"}, ensure_ascii=False,
                           separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)



import contextlib


@contextlib.asynccontextmanager
async def webapp_client():
    """Приложение с базой в памяти, двумя пользователями и одной записью еды."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def get_session():
        async with maker() as session:
            yield session

    import webapp.api as api_module

    original = api_module.get_session
    api_module.get_session = get_session
    db_module.get_session = get_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with maker() as session:
        for uid in (USER_ID, OTHER_ID):
            session.add(User(
                id=uid, full_name="Лилия", gender=GenderEnum.FEMALE, age=30, height_cm=165,
                current_weight_kg=60, target_weight_kg=55, goal=GoalEnum.LOSE_WEIGHT,
                diet_type=DietTypeEnum.REGULAR, timezone="Europe/Moscow",
                daily_calories=1600, daily_protein_g=120, daily_fat_g=48,
                daily_carbs_g=160, daily_water_ml=2100, onboarding_completed=True))
        await session.commit()
        meal = await save_meal(
            session, user_id=USER_ID,
            analysis=FoodAnalysis(name="Овсянка", weight_g=250, calories=320, protein_g=9,
                                  fat_g=7, carbs_g=55, confidence="medium", comment=""),
            source=MealSourceEnum.PHOTO, meal_type=MealTypeEnum.BREAKFAST)
        meal_id = meal.id

    from webapp.server import create_app

    client = TestClient(TestServer(create_app()))
    await client.start_server()
    try:
        yield client, meal_id
    finally:
        await client.close()
        api_module.get_session = original


async def call(client, method, path, *, user_id=USER_ID, json_body=None, signed=True):
    headers = {"X-Telegram-Init-Data": init_data(user_id)} if signed else {}
    return await client.request(method, path, headers=headers, json=json_body)


def run(scenario):
    """Каждый тест — отдельный сценарий в собственном цикле событий."""
    asyncio.run(scenario())


def test_today_returns_norms_meals_and_water():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "GET", "/api/today")
            assert response.status == 200
            data = await response.json()
            assert data["norms"]["calories"] == 1600
            assert data["totals"]["calories"] == 320
            assert len(data["meals"]) == 1
            assert data["meals"][0]["name"] == "Овсянка"
            assert data["totals"]["water_ml"] == 0
    run(scenario)


def test_request_without_signature_is_rejected():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "GET", "/api/today", signed=False)
            assert response.status == 401
    run(scenario)


def test_water_adds_up_and_undo_removes():
    async def scenario():
        async with webapp_client() as (client, _):
            await call(client, "POST", "/api/water", json_body={"amount_ml": 250})
            response = await call(client, "POST", "/api/water", json_body={"amount_ml": 500})
            assert (await response.json())["water_ml"] == 750

            response = await call(client, "POST", "/api/water/undo")
            data = await response.json()
            assert data["water_ml"] == 250 and data["removed_ml"] == 500
    run(scenario)


def test_water_rejects_absurd_amount():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/water", json_body={"amount_ml": 99999})
            assert response.status == 400
    run(scenario)


def test_meal_weight_edit_rescales_nutrition():
    async def scenario():
        async with webapp_client() as (client, meal_id):
            response = await call(client, "PATCH", f"/api/meals/{meal_id}",
                                  json_body={"weight_g": 125})
            data = await response.json()
            assert data["weight_g"] == 125
            assert data["calories"] == 160  # половина порции — половина калорий
    run(scenario)


def test_cannot_touch_someone_elses_meal():
    """Главная проверка безопасности: чужие записи недоступны."""
    async def scenario():
        async with webapp_client() as (client, meal_id):
            response = await call(client, "PATCH", f"/api/meals/{meal_id}",
                                  user_id=OTHER_ID, json_body={"weight_g": 100})
            assert response.status == 404

            response = await call(client, "DELETE", f"/api/meals/{meal_id}", user_id=OTHER_ID)
            assert response.status == 404
    run(scenario)


def test_meal_can_be_deleted():
    async def scenario():
        async with webapp_client() as (client, meal_id):
            assert (await call(client, "DELETE", f"/api/meals/{meal_id}")).status == 200
            data = await (await call(client, "GET", "/api/today")).json()
            assert data["meals"] == []
    run(scenario)


def test_supplement_add_and_mark():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/supplements",
                                  json_body={"name": "Витамин D", "dose": "5000 МЕ",
                                             "schedule_type": "daily", "reminder_time": "09:00"})
            assert response.status == 200
            supplement_id = (await response.json())["id"]

            data = await (await call(client, "GET", "/api/today")).json()
            assert data["supplements"][0]["name"] == "Витамин D"
            assert data["supplements"][0]["taken"] is False

            await call(client, "POST", f"/api/supplements/{supplement_id}/mark",
                       json_body={"skipped": False})
            data = await (await call(client, "GET", "/api/today")).json()
            assert data["supplements"][0]["taken"] is True
    run(scenario)


def test_supplement_of_another_user_is_not_markable():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/supplements", json_body={"name": "Магний"})
            supplement_id = (await response.json())["id"]

            response = await call(client, "POST", f"/api/supplements/{supplement_id}/mark",
                                  user_id=OTHER_ID)
            assert response.status == 404
    run(scenario)
