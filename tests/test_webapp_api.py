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


def test_progress_returns_series_and_summary():
    async def scenario():
        async with webapp_client() as (client, _):
            # два замера: вчера и сегодня
            await call(client, "POST", "/api/measurements", json_body={"weight_kg": 62})
            response = await call(client, "GET", "/api/progress?metric=weight&period=month")
            assert response.status == 200
            data = await response.json()

            assert data["title"] == "Вес"
            assert data["unit"] == "кг"
            assert data["goal"] == 55          # целевой вес из профиля
            assert data["points"][-1]["value"] == 62
            assert data["summary"]["current_weight"] == 62
            assert data["summary"]["streak"] >= 1   # еда за сегодня записана в фикстуре
    run(scenario)


def test_progress_calories_metric_uses_meals():
    async def scenario():
        async with webapp_client() as (client, _):
            data = await (await call(client, "GET", "/api/progress?metric=calories")).json()
            assert data["title"] == "Калории"
            assert data["points"][-1]["value"] == 320   # единственный приём пищи в фикстуре
            assert data["goal"] is None                 # у калорий нет линии цели
    run(scenario)


def test_measurement_validates_range():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/measurements", json_body={"weight_kg": 900})
            assert response.status == 400

            response = await call(client, "POST", "/api/measurements", json_body={})
            assert response.status == 400
    run(scenario)


def test_photo_of_another_user_is_not_readable():
    async def scenario():
        async with webapp_client() as (client, _):
            import io
            form = {"photo": io.BytesIO(b"\xff\xd8fake-jpeg")}
            response = await client.post(
                "/api/photos",
                headers={"X-Telegram-Init-Data": init_data(USER_ID)},
                data=form,
            )
            assert response.status == 200
            photo_id = (await response.json())["id"]

            assert (await call(client, "GET", f"/api/photos/{photo_id}")).status == 200
            other = await call(client, "GET", f"/api/photos/{photo_id}", user_id=OTHER_ID)
            assert other.status == 404
    run(scenario)


def _seed_workouts_sync(client):
    """Библиотека упражнений в тестовой базе."""
    from seed.loader import seed_workouts
    import webapp.api as api_module
    return api_module.get_session


def test_workouts_returns_program_for_place_and_level():
    async def scenario():
        async with webapp_client() as (client, _):
            from seed.loader import seed_workouts
            import webapp.api as api_module
            async with api_module.get_session() as session:
                await seed_workouts(session)

            data = await (await call(client, "GET", "/api/workouts?location=home&level=beginner")).json()
            assert data["selected"] == "home_beginner"
            assert len(data["exercises"]) == 6
            first = data["exercises"][0]
            assert first["sets"] and first["reps"] and first["rest_seconds"]
            assert first["calories"] > 0            # расход посчитан по MET
            assert first["demo_url"].startswith("https://")
            assert len(data["cardio"]) == 7
            assert data["cardio"][0]["is_cardio"] is True
    run(scenario)


def test_gym_program_differs_from_home():
    async def scenario():
        async with webapp_client() as (client, _):
            from seed.loader import seed_workouts
            import webapp.api as api_module
            async with api_module.get_session() as session:
                await seed_workouts(session)

            home = await (await call(client, "GET", "/api/workouts?location=home&level=beginner")).json()
            gym = await (await call(client, "GET", "/api/workouts?location=gym&level=beginner")).json()
            assert home["selected"] != gym["selected"]
            assert {e["name"] for e in home["exercises"]} != {e["name"] for e in gym["exercises"]}
    run(scenario)


def test_workout_log_counts_calories_and_updates_week():
    async def scenario():
        async with webapp_client() as (client, _):
            from seed.loader import seed_workouts
            import webapp.api as api_module
            async with api_module.get_session() as session:
                await seed_workouts(session)

            data = await (await call(client, "GET", "/api/workouts")).json()
            ids = [e["id"] for e in data["exercises"][:3]]

            result = await (await call(client, "POST", "/api/workouts/log",
                                       json_body={"exercise_ids": ids})).json()
            assert result["logged"] == 3
            assert result["calories"] > 0
            assert result["minutes"] > 0
            assert result["week"]["workouts"] == 1      # одна тренировка за неделю
            assert result["week"]["exercises"] == 3
    run(scenario)


def test_workout_log_requires_exercises():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/workouts/log",
                                  json_body={"exercise_ids": []})
            assert response.status == 400
    run(scenario)


def test_cardio_minutes_are_validated():
    async def scenario():
        async with webapp_client() as (client, _):
            from seed.loader import seed_workouts
            import webapp.api as api_module
            async with api_module.get_session() as session:
                await seed_workouts(session)

            data = await (await call(client, "GET", "/api/workouts")).json()
            cardio_id = data["cardio"][0]["id"]

            response = await call(client, "POST", "/api/workouts/log",
                                  json_body={"exercise_ids": [cardio_id], "minutes": 999})
            assert response.status == 400

            result = await (await call(client, "POST", "/api/workouts/log",
                                       json_body={"exercise_ids": [cardio_id], "minutes": 45})).json()
            # Ходьба (MET 4.3) 45 минут при весе 60 кг ≈ 190 ккал.
            assert 150 < result["calories"] < 250
    run(scenario)
