"""Проверка API мини-приложения: настоящие HTTP-запросы к настоящей базе."""

import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
import db as db_module
from models import (Base, DietTypeEnum, GenderEnum, GoalEnum, MealSourceEnum, MealTypeEnum,
                    SubscriptionSource, User)
from services import context
from services.subscriptions import activate
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

# Тестам иногда нужно залезть в базу мимо API — например, состарить подписку.
maker_holder: dict = {}


@contextlib.asynccontextmanager
async def webapp_client(bot=None):
    """Приложение с базой в памяти, двумя пользователями и одной записью еды."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    maker_holder["maker"] = maker

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
        # Справочник питания — источник блюд для подбора.
        from seed.nutrition.loader import seed_nutrition

        await seed_nutrition(session)
        for uid in (USER_ID, OTHER_ID):
            session.add(User(
                id=uid, full_name="Лилия", gender=GenderEnum.FEMALE, age=30, height_cm=165,
                current_weight_kg=60, target_weight_kg=55, goal=GoalEnum.LOSE_WEIGHT,
                diet_type=DietTypeEnum.REGULAR, timezone="Europe/Moscow",
                daily_calories=1600, daily_protein_g=120, daily_fat_g=48,
                daily_carbs_g=160, daily_fiber_g=22, daily_water_ml=2100,
                onboarding_completed=True))
        await session.commit()
        # Приложение живёт по подписке — в тестах она у обоих есть.
        for uid in (USER_ID, OTHER_ID):
            await activate(session, uid, days=30, source=SubscriptionSource.MANUAL)
        meal = await save_meal(
            session, user_id=USER_ID,
            analysis=FoodAnalysis(name="Овсянка", weight_g=250, calories=320, protein_g=9,
                                  fat_g=7, carbs_g=55, fiber_g=6, confidence="medium",
                                  comment=""),
            source=MealSourceEnum.PHOTO, meal_type=MealTypeEnum.BREAKFAST)
        meal_id = meal.id

    from webapp.server import create_app

    client = TestClient(TestServer(create_app(bot)))
    await client.start_server()
    try:
        yield client, meal_id
    finally:
        await client.close()
        api_module.get_session = original
        # Без этого рабочий поток aiosqlite иногда доживает до закрытия цикла
        # и роняет предупреждение в случайный тест.
        await engine.dispose()


async def call(client, method, path, *, user_id=USER_ID, json_body=None, signed=True,
               timezone=None):
    headers = {"X-Telegram-Init-Data": init_data(user_id)} if signed else {}
    if timezone:
        headers["X-Timezone"] = timezone
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
            # Клетчатка — отдельная цель со своей нормой, не часть калорий.
            assert data["norms"]["fiber_g"] == 22
            assert data["totals"]["fiber_g"] == 6
            assert data["meals"][0]["fiber_g"] == 6
    run(scenario)


def test_today_includes_game_state_with_quests():
    async def scenario():
        async with webapp_client() as (client, _):
            data = await (await call(client, "GET", "/api/today")).json()
            game = data["game"]
            assert game["level"] == 1
            assert game["quests_total"] >= 5
            # Один приём пищи из трёх — задание про еду ещё не закрыто.
            quests = {q["code"]: q for q in game["quests"]}
            assert quests["meals"]["done"] is False
            assert quests["meals"]["hint"] == "1 из 3"
            # Первая запись еды — это уже награда.
            assert {a["code"] for a in game["new_awards"]} == {"first_step"}
    run(scenario)


def test_progress_carries_the_body_figure():
    async def scenario():
        async with webapp_client() as (client, _):
            data = await (await call(client, "GET", "/api/progress")).json()
            body = data["body"]

            assert body["now"]["hip"] > body["now"]["waist"]
            # Цель 55 кг при весе 60 — фигура-ориентир должна быть уже.
            assert body["goal"]["waist"] < body["now"]["waist"]
            # Замеров ещё нет, значит фигура примерная и так и помечена.
            assert body["estimated"] is True
            assert any("До твоей цели" in item["title"] for item in body["insights"])
    run(scenario)


def test_measurement_reshapes_the_figure():
    """Ради этого фигура и считается, а не рисуется картинкой."""
    async def scenario():
        async with webapp_client() as (client, _):
            before = (await (await call(client, "GET", "/api/progress")).json())["body"]

            await call(client, "POST", "/api/measurements", json_body={"waist_cm": 62})

            after = (await (await call(client, "GET", "/api/progress")).json())["body"]
            assert after["now"]["waist"] < before["now"]["waist"]

            waist_zone = next(z for z in after["zones"] if z["code"] == "waist")
            assert waist_zone["has_data"] is True and waist_zone["value"] == 62
    run(scenario)


def test_marking_stress_closes_its_quest():
    """Пожелание из живого теста: стресс тоже влияет на вес — по нему должен
    быть свой квест, и он закрывается той же кнопкой, что и остальное
    состояние (/api/checkin)."""
    async def scenario():
        async with webapp_client() as (client, _):
            before = (await (await call(client, "GET", "/api/today")).json())["game"]
            quests_before = {q["code"]: q for q in before["quests"]}
            assert quests_before["stress"]["done"] is False

            response = await call(client, "POST", "/api/checkin",
                                   json_body={"stress": "средний"})
            assert response.status == 200

            after = (await (await call(client, "GET", "/api/today")).json())["game"]
            quests_after = {q["code"]: q for q in after["quests"]}
            assert quests_after["stress"]["done"] is True
    run(scenario)


def test_closing_a_quest_gives_xp_and_a_streak():
    async def scenario():
        async with webapp_client() as (client, _):
            for _ in range(2):
                await call(client, "POST", "/api/meals", json_body={
                    "name": "Салат", "weight_g": 200, "calories": 150,
                    "protein_g": 4, "fat_g": 9, "carbs_g": 10, "fiber_g": 5})

            game = (await (await call(client, "GET", "/api/today")).json())["game"]
            assert "meals" in game["just_completed"]
            assert game["xp_today"] == 15
            assert game["streak"] == 1
    run(scenario)


def test_moment_is_recognized_but_not_saved_until_confirmed():
    """Догадки модели человек должен увидеть до записи в дневник."""
    async def scenario():
        async with webapp_client() as (client, _):
            import webapp.api as api_module
            from services.moments import build_moment

            payload = {
                "summary": "Завтрак", "food_name": "Овсянка", "weight_g": 250,
                "calories": 320, "protein_g": 9, "fat_g": 7, "carbs_g": 49, "fiber_g": 6,
                "energy": 7, "focus": 0, "mood": "бодро", "stress": "", "sleep_hours": 0,
                "comment": "порция каши",
            }

            async def fake_analyze(text, **kwargs):
                return build_moment(payload, text=text, at="08:40")

            original = api_module.analyze_moment
            api_module.analyze_moment = fake_analyze
            try:
                before = await (await call(client, "GET", "/api/today")).json()

                data = await (await call(client, "POST", "/api/moment", json_body={
                    "text": "Позавтракала овсянкой, чувствую себя бодрее"})).json()
                assert data["summary"] == "Завтрак"
                assert {row["label"] for row in data["facts"]} >= {"Событие", "Энергия",
                                                                   "Настроение", "Время"}

                # Пока не подтвердили — в дневнике ничего не прибавилось.
                middle = await (await call(client, "GET", "/api/today")).json()
                assert middle["totals"]["calories"] == before["totals"]["calories"]

                saved = await (await call(client, "POST", "/api/moment/confirm",
                                          json_body={"moment": data["moment"]})).json()
                assert saved["saved"] == ["еда", "самочувствие"]

                after = await (await call(client, "GET", "/api/today")).json()
                assert after["totals"]["calories"] == before["totals"]["calories"] + 320
                assert after["state"]["energy"] == 7
                assert after["state"]["mood"] == "бодро"
                # Съеденное и самочувствие встали в ленту дня, причём тем
                # временем, которое стояло в карточке.
                kinds = {event["kind"] for event in after["timeline"]}
                assert {"meal", "state"} <= kinds
                assert any(event["time"] == "08:40" and event["kind"] == "meal"
                           for event in after["timeline"])
            finally:
                api_module.analyze_moment = original
    run(scenario)


def test_moment_without_text_is_rejected():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/moment", json_body={"text": "  "})
            assert response.status == 400
    run(scenario)


def test_checkin_saves_state_tiles():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/checkin",
                                  json_body={"energy": 8, "mood": "спокойно"})
            assert response.status == 200

            data = await (await call(client, "GET", "/api/today")).json()
            assert data["state"]["energy"] == 8
            assert data["state"]["mood"] == "спокойно"
    run(scenario)


def test_checkin_rejects_empty_and_out_of_range():
    async def scenario():
        async with webapp_client() as (client, _):
            assert (await call(client, "POST", "/api/checkin", json_body={})).status == 400
            assert (await call(client, "POST", "/api/checkin",
                               json_body={"energy": 42})).status == 400
    run(scenario)


def test_app_is_closed_without_a_subscription(monkeypatch):
    """Кончилась подписка — данные на месте, но приложение просит оплату."""
    # Без владельца платный доступ выключен, поэтому включаем его явно.
    monkeypatch.setattr(config, "PAYWALL", True)

    async def scenario():
        async with webapp_client() as (client, _):
            from services.subscriptions import now
            from models import Subscription
            from datetime import timedelta
            from sqlalchemy import select

            async with maker_holder["maker"]() as session:
                row = (await session.execute(
                    select(Subscription).where(Subscription.user_id == USER_ID)
                )).scalar_one()
                row.expires_at = now() - timedelta(days=1)
                await session.commit()

            response = await call(client, "GET", "/api/today")
            assert response.status == 402
            body = await response.json()
            assert body["need_subscription"] is True
            assert body["price_stars"] > 0
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
            assert data["fiber_g"] == 3      # и половина клетчатки
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


def test_thigh_measurement_is_saved_and_charted():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/measurements",
                                  json_body={"thigh_cm": 58.5})
            assert response.status == 200

            data = await (await call(client, "GET", "/api/progress?metric=thigh&period=month")).json()
            # Заголовок пишем полностью: «бёдра» и «бедро» рядом не различить.
            assert data["title"] == "Обхват ноги"
            assert data["points"][-1]["value"] == 58.5
    run(scenario)


def test_thigh_measurement_validates_range():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/measurements",
                                  json_body={"thigh_cm": 300})
            assert response.status == 400
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

            data = await (await call(client, "GET", "/api/workouts?category=body&style=mix")).json()
            assert data["selected"] == "home_beginner"
            assert len(data["exercises"]) == 6
            first = data["exercises"][0]
            assert first["sets"] and first["reps"] and first["rest_seconds"]
            assert first["calories"] > 0            # расход посчитан по MET
            assert first["demo_url"].startswith("https://")
            assert len(data["cardio"]) == 7
            assert data["cardio"][0]["is_cardio"] is True
    run(scenario)


def test_styles_give_different_programs():
    async def scenario():
        async with webapp_client() as (client, _):
            from seed.loader import seed_workouts
            import webapp.api as api_module
            async with api_module.get_session() as session:
                await seed_workouts(session)

            mix = await (await call(client, "GET", "/api/workouts?category=body&style=mix")).json()
            yoga = await (await call(client, "GET", "/api/workouts?category=body&style=yoga")).json()

            assert mix["selected"] != yoga["selected"]
            assert {e["name"] for e in mix["exercises"]} != {e["name"] for e in yoga["exercises"]}
            # Формы занятий предлагаются только для тела.
            assert {s["code"] for s in mix["styles"]} >= {"mix", "yoga", "pilates", "bands"}


def test_face_category_has_its_own_programs_and_no_calories():
    async def scenario():
        async with webapp_client() as (client, _):
            from seed.loader import seed_workouts
            import webapp.api as api_module
            async with api_module.get_session() as session:
                await seed_workouts(session)

            data = await (await call(client, "GET", "/api/workouts?category=face")).json()

            assert data["selected"] in {"face_yoga", "face_massage"}
            assert len(data["programs"]) == 2
            # Расход калорий у гимнастики для лица ничтожен — не показываем.
            assert data["show_calories"] is False
            # Честная оговорка о том, чем это является и чем нет.
            assert "косметологию" in data["note"] or "врач" in data["note"]
            assert data["styles"] == []          # у лица нет форм занятий
            assert data["cardio"] == []          # и отдельного кардио тоже
    run(scenario)


def test_eyes_and_posture_categories_exist():
    async def scenario():
        async with webapp_client() as (client, _):
            from seed.loader import seed_workouts
            import webapp.api as api_module
            async with api_module.get_session() as session:
                await seed_workouts(session)

            eyes = await (await call(client, "GET", "/api/workouts?category=eyes")).json()
            assert eyes["selected"] == "eyes_daily"
            assert "офтальмолог" in eyes["note"]
            assert eyes["show_calories"] is False

            posture = await (await call(client, "GET", "/api/workouts?category=posture")).json()
            assert posture["selected"] == "posture_daily"
            assert posture["show_calories"] is True   # осанка — это всё-таки нагрузка

            categories = {c["code"] for c in eyes["categories"]}
            assert categories == {"body", "face", "eyes", "posture"}
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


def test_page_carries_asset_versions_so_telegram_cannot_serve_a_stale_app():
    """Без метки версии Telegram неделями показывает старое приложение —
    именно так новая карточка «Твоё тело» до человека и не доехала."""
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "GET", "/", signed=False)
            page = await response.text()

            assert "/static/app.js?v=" in page
            assert "/static/styles.css?v=" in page
            assert "no-store" in response.headers.get("Cache-Control", "")
    run(scenario)


def test_today_carries_the_daily_line():
    """Фраза дня приходит вместе с профилем и одинакова весь день."""
    async def scenario():
        async with webapp_client() as (client, _):
            first = (await (await call(client, "GET", "/api/today")).json())["profile"]
            again = (await (await call(client, "GET", "/api/today")).json())["profile"]

            assert first["line"]
            assert first["line"] == again["line"]
    run(scenario)


def test_app_learns_the_real_timezone_from_the_device():
    """Пояс никто не спрашивал, и у всех оставалась Москва: у человека из
    другого пояса утренняя еда уезжала во вчера."""
    async def scenario():
        async with webapp_client() as (client, _):
            await call(client, "GET", "/api/today", timezone="Asia/Vladivostok")

            async with maker_holder["maker"]() as session:
                user = await session.get(User, USER_ID)
                assert user.timezone == "Asia/Vladivostok"
    run(scenario)


def test_nonsense_timezone_is_ignored():
    """Заголовок приходит снаружи — чушь в профиль попасть не должна."""
    async def scenario():
        async with webapp_client() as (client, _):
            await call(client, "GET", "/api/today", timezone="Марс/Олимп")

            async with maker_holder["maker"]() as session:
                user = await session.get(User, USER_ID)
                assert user.timezone == "Europe/Moscow"
    run(scenario)


# --- Кубик через настоящий HTTP -------------------------------------------

def test_cube_picks_the_hunger_level_from_the_diary_itself():
    """Человек у полки не знает свой остаток — сервер обязан посчитать сам."""
    async def scenario():
        async with webapp_client() as (client, _):
            # Уровень не передаём: именно этот путь и ломался.
            response = await call(client, "POST", "/api/cube",
                                  json_body={"craving": "salty", "no_spoon": True})
            assert response.status == 200
            body = await response.json()
            assert body["level"] in {"light", "normal", "hungry", "meal"}
            assert body["cubes"]
            for item in body["cubes"]:
                assert item["items"] and item["kcal_high"] > item["kcal_low"]
    run(scenario)


def test_cube_in_store_mode_answers_with_three_labelled_options():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/cube",
                                  json_body={"shop": True, "craving": "sweet"})
            assert response.status == 200
            cubes = (await response.json())["cubes"]
            assert [item["label"] for item in cubes] == \
                ["Самый простой", "Посытнее", "Запасной"]
    run(scenario)


def test_cube_builds_only_from_what_is_in_the_basket():
    async def scenario():
        async with webapp_client() as (client, _):
            basket = ["kefir", "banana", "walnut"]
            response = await call(client, "POST", "/api/cube",
                                  json_body={"level": "normal", "basket": basket})
            assert response.status == 200
            for item in (await response.json())["cubes"]:
                assert {part["code"] for part in item["items"]} <= set(basket)
    run(scenario)


async def upload_shelf(client, *, user_id=USER_ID, content=b"\xff\xd8\xff\xe0jpeg"):
    """Загрузка фото полки идёт формой, а не JSON — как настоящий снимок."""
    form = aiohttp.FormData()
    form.add_field("photo", content, filename="shelf.jpg", content_type="image/jpeg")
    return await client.request("POST", "/api/cube/shelf",
                                headers={"X-Telegram-Init-Data": init_data(user_id)},
                                data=form)


def _fake_shelf(monkeypatch, codes, other=()):
    from services import shelf_vision

    async def recognize(image_bytes, names, *, media_type="image/jpeg", on_usage=None):
        assert image_bytes, "фото должно доехать до распознавания"
        # Расход записывается по настоящему ответу модели — подделываем и его.
        if on_usage is not None:
            on_usage(_FakeUsage())
        return shelf_vision.Shelf(codes=tuple(codes), other=tuple(other))

    monkeypatch.setattr(shelf_vision, "recognize", recognize)


class _FakeUsage:
    input_tokens = 1500
    output_tokens = 40
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _CrashBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


def test_a_broken_screen_tells_the_person_and_the_owner(monkeypatch):
    """Ошибка в приложении уходила только в лог — то есть в никуда."""
    async def scenario():
        bot = _CrashBot()
        async with webapp_client(bot) as (client, _):
            import webapp.api as api_module
            from services import alerts, crashes

            crashes.reset()
            alerts.reset()
            monkeypatch.setattr(crashes.config, "ADMIN_IDS", [246959020])
            monkeypatch.setattr(alerts.config, "ADMIN_IDS", [246959020])

            def explode(*args, **kwargs):
                raise TypeError("нет такого параметра")

            monkeypatch.setattr(api_module, "get_today_totals", explode)

            response = await call(client, "GET", "/api/today")
            assert response.status == 500
            body = await response.json()
            # Человеку — честно и без трассировки.
            assert "записи целы" in body["error"]
            assert ".py" not in body["error"]

            # Владельцу — где именно сломалось.
            (_, text), = bot.sent
            assert "нет такого параметра" in text
            assert "GET /api/today" in text
            assert f"{USER_ID}" in text

            crashes.reset()
            alerts.reset()
    run(scenario)


def test_a_broken_screen_on_the_phone_also_reaches_the_owner(monkeypatch):
    """Ошибка в браузере не видна нигде: на сервере при этом всё в порядке."""
    async def scenario():
        bot = _CrashBot()
        async with webapp_client(bot) as (client, _):
            from services import alerts, crashes

            crashes.reset()
            alerts.reset()
            monkeypatch.setattr(crashes.config, "ADMIN_IDS", [246959020])
            monkeypatch.setattr(alerts.config, "ADMIN_IDS", [246959020])

            response = await call(client, "POST", "/api/crash", json_body={
                "message": "undefined is not an object (evaluating 'a.b')",
                "place": "/static/app.js:1204", "screen": "cube"})
            assert response.status == 200

            (_, text), = bot.sent
            assert "a.b" in text and "app.js:1204" in text
            assert "cube" in text and f"{USER_ID}" in text

            # Сломанный экран умеет сыпать ошибками без конца — владельцу
            # это должно прийти один раз.
            for _ in range(5):
                await call(client, "POST", "/api/crash", json_body={
                    "message": "undefined is not an object (evaluating 'a.b')",
                    "place": "/static/app.js:1204", "screen": "cube"})
            assert len(bot.sent) == 1

            crashes.reset()
            alerts.reset()
    run(scenario)


def test_a_crash_report_is_trimmed_before_it_reaches_the_chat(monkeypatch):
    """Текст приходит с телефона человека — в чат владельцу не должно уехать
    полотно на весь экран."""
    async def scenario():
        bot = _CrashBot()
        async with webapp_client(bot) as (client, _):
            from services import alerts, crashes

            crashes.reset()
            alerts.reset()
            monkeypatch.setattr(crashes.config, "ADMIN_IDS", [246959020])
            monkeypatch.setattr(alerts.config, "ADMIN_IDS", [246959020])

            await call(client, "POST", "/api/crash",
                       json_body={"message": "я" * 5000, "place": "ж" * 5000})
            (_, text), = bot.sent
            assert len(text) < 1000

            crashes.reset()
            alerts.reset()
    run(scenario)


def test_an_empty_crash_report_is_ignored():
    async def scenario():
        bot = _CrashBot()
        async with webapp_client(bot) as (client, _):
            response = await call(client, "POST", "/api/crash", json_body={"message": ""})
            assert response.status == 200
            assert bot.sent == []
    run(scenario)


def test_the_crash_endpoint_needs_a_signature_like_everything_else():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/crash", signed=False,
                                  json_body={"message": "боль"})
            assert response.status == 401
    run(scenario)


def test_a_problem_from_the_app_reaches_the_owner_with_the_screen(monkeypatch):
    """Человек споткнулся на экране — выгонять его в чат ради жалобы значит
    не получить жалобу вовсе."""
    async def scenario():
        bot = _CrashBot()
        async with webapp_client(bot) as (client, _):
            from services import feedback

            feedback.reset()
            monkeypatch.setattr(feedback.config, "ADMIN_IDS", [246959020])
            monkeypatch.setattr(config, "ADMIN_IDS", [246959020])

            response = await call(client, "POST", "/api/feedback", json_body={
                "text": "посчитало вдвое больше, чем я съела", "screen": "today"})
            assert response.status == 200

            (chat_id, text), = bot.sent
            assert chat_id == 246959020
            assert "вдвое больше" in text
            assert "today" in text and f"{USER_ID}" in text
            feedback.reset()
    run(scenario)


def test_an_empty_problem_from_the_app_is_refused(monkeypatch):
    async def scenario():
        bot = _CrashBot()
        async with webapp_client(bot) as (client, _):
            from services import feedback

            feedback.reset()
            monkeypatch.setattr(feedback.config, "ADMIN_IDS", [246959020])
            monkeypatch.setattr(config, "ADMIN_IDS", [246959020])

            response = await call(client, "POST", "/api/feedback",
                                  json_body={"text": "   "})
            assert response.status == 400
            assert bot.sent == []
            feedback.reset()
    run(scenario)


def test_the_app_cannot_flood_the_owner_either(monkeypatch):
    async def scenario():
        bot = _CrashBot()
        async with webapp_client(bot) as (client, _):
            from services import feedback

            feedback.reset()
            monkeypatch.setattr(feedback.config, "ADMIN_IDS", [246959020])
            monkeypatch.setattr(config, "ADMIN_IDS", [246959020])

            statuses = []
            for _ in range(feedback.PER_HOUR + 2):
                response = await call(client, "POST", "/api/feedback",
                                      json_body={"text": "опять не так"})
                statuses.append(response.status)

            assert statuses.count(200) == feedback.PER_HOUR
            assert 429 in statuses
            assert len(bot.sent) == feedback.PER_HOUR
            feedback.reset()
    run(scenario)


def test_the_problem_form_needs_a_signature_like_everything_else():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/feedback", signed=False,
                                  json_body={"text": "боль"})
            assert response.status == 401
    run(scenario)


def test_shelf_photo_answers_with_names_the_person_can_check(monkeypatch):
    """Сначала показываем, что увидели, и только потом собираем набор."""
    async def scenario():
        async with webapp_client() as (client, _):
            _fake_shelf(monkeypatch, ["kefir", "banana"], other=["авокадо"])
            response = await upload_shelf(client)
            assert response.status == 200
            body = await response.json()
            assert body["codes"] == ["kefir", "banana"]
            # Кодов человек не видит — он видит названия из нашего справочника.
            assert [item["code"] for item in body["items"]] == ["kefir", "banana"]
            names = [item["name"] for item in body["items"]]
            assert all(names) and "кефир" in names[0].lower()
            # Незнакомое не прячем: иначе человек решит, что бот его проглядел.
            assert body["other"] == ["авокадо"]
    run(scenario)


def test_shelf_photo_feeds_the_cube_with_exactly_what_was_recognized(monkeypatch):
    """Ради этого всё и делалось: снял полку — собрал набор из того, что на ней."""
    async def scenario():
        async with webapp_client() as (client, _):
            _fake_shelf(monkeypatch, ["kefir", "banana", "walnut", "crispbread"])
            codes = (await (await upload_shelf(client)).json())["codes"]

            response = await call(client, "POST", "/api/cube",
                                  json_body={"level": "normal", "basket": codes})
            cubes = (await response.json())["cubes"]
            assert cubes
            for item in cubes:
                assert {part["code"] for part in item["items"]} <= set(codes)
    run(scenario)


def test_shelf_photo_gives_a_smaller_set_instead_of_an_empty_screen(monkeypatch):
    """С пустым дневником бот метит в «почти обед», а на полке четыре продукта.

    Режим голода в этот момент выбрали мы сами, а не человек. Значит, его и
    надо уступить: снял полку — получил набор, а не объяснение, почему нет.
    """
    async def scenario():
        async with webapp_client() as (client, _):
            _fake_shelf(monkeypatch, ["kefir", "banana", "crispbread", "walnut"])
            codes = (await (await upload_shelf(client)).json())["codes"]

            # Уровень не передаём — ровно так и ходит приложение после фото.
            body = await (await call(client, "POST", "/api/cube",
                                     json_body={"basket": codes})).json()
            assert body["cubes"], "из полки должно собираться хоть что-то"
            assert body["level"] in ("light", "normal", "hungry")
            for item in body["cubes"]:
                assert {part["code"] for part in item["items"]} <= set(codes)
    run(scenario)


def test_a_hunger_level_the_person_chose_is_never_quietly_lowered(monkeypatch):
    """Уступаем только собственную догадку. Просьбу человека — нет."""
    async def scenario():
        async with webapp_client() as (client, _):
            _fake_shelf(monkeypatch, ["kefir", "banana", "crispbread", "walnut"])
            codes = (await (await upload_shelf(client)).json())["codes"]

            body = await (await call(client, "POST", "/api/cube",
                                     json_body={"level": "meal",
                                                "basket": codes})).json()
            assert body["level"] == "meal"
    run(scenario)


def test_shelf_photo_is_paid_for_and_counted_against_the_daily_limit(monkeypatch):
    """Снимок полки стоит те же деньги, что снимок блюда, и лимит у них общий."""
    async def scenario():
        async with webapp_client() as (client, _):
            from services import usage

            _fake_shelf(monkeypatch, ["kefir"])
            assert (await upload_shelf(client)).status == 200

            async with maker_holder["maker"]() as session:
                spend = await usage.spent_today(session)
                assert spend.by_kind["shelf"] > 0
                left = await usage.photo_limit_left(session, USER_ID)
                assert left == config.PHOTO_LIMIT_PER_DAY - 1
    run(scenario)


def test_shelf_photo_stops_when_the_person_is_out_of_photos(monkeypatch):
    async def scenario():
        async with webapp_client() as (client, _):
            monkeypatch.setattr(config, "PHOTO_LIMIT_PER_DAY", 1)
            _fake_shelf(monkeypatch, ["kefir"])
            assert (await upload_shelf(client)).status == 200

            second = await upload_shelf(client)
            assert second.status == 429
            assert "корзине руками" in (await second.json())["error"]
    run(scenario)


def test_shelf_photo_stops_when_the_daily_budget_is_spent(monkeypatch):
    """Потолок расходов останавливает распознавание, а не всё приложение."""
    async def scenario():
        async with webapp_client() as (client, _):
            monkeypatch.setattr(config, "DAILY_COST_LIMIT_USD", 0.0001)
            _fake_shelf(monkeypatch, ["kefir"])
            assert (await upload_shelf(client)).status == 200

            assert (await upload_shelf(client)).status == 429
            # Подбор руками при этом продолжает работать.
            manual = await call(client, "POST", "/api/cube",
                                json_body={"level": "normal", "basket": ["kefir", "banana"]})
            assert manual.status == 200
    run(scenario)


def test_shelf_photo_refuses_when_the_disk_is_full(monkeypatch):
    async def scenario():
        async with webapp_client() as (client, _):
            import webapp.api as api_module

            _fake_shelf(monkeypatch, ["kefir"])
            monkeypatch.setattr(api_module, "disk_usage",
                                lambda: SimpleNamespace(full=True, percent=99))
            response = await upload_shelf(client)
            assert response.status == 507
    run(scenario)


def test_shelf_photo_explains_a_model_failure_instead_of_crashing(monkeypatch):
    async def scenario():
        async with webapp_client() as (client, _):
            from services import shelf_vision
            from services.food_vision import FoodRecognitionError

            async def failing(*args, **kwargs):
                raise FoodRecognitionError("Claude ответил ошибкой (529).")

            monkeypatch.setattr(shelf_vision, "recognize", failing)
            response = await upload_shelf(client)
            assert response.status == 502
            assert "529" in (await response.json())["error"]
    run(scenario)


def test_shelf_photo_needs_a_signature_like_everything_else():
    async def scenario():
        async with webapp_client() as (client, _):
            form = aiohttp.FormData()
            form.add_field("photo", b"jpeg", filename="shelf.jpg")
            response = await client.request("POST", "/api/cube/shelf", data=form)
            assert response.status == 401
    run(scenario)


def test_the_basket_list_comes_with_names():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "GET", "/api/cube/basket")
            assert response.status == 200
            rows = (await response.json())["rows"]
            assert [row["title"] for row in rows][:2] == ["Выпить", "Белок"]
            for row in rows:
                assert row["items"] and all(item["name"] for item in row["items"])
    run(scenario)


def test_cube_needs_a_signature_like_everything_else():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/cube", signed=False,
                                  json_body={"level": "normal"})
            assert response.status == 401
    run(scenario)


# --- «Твой ход» через настоящий HTTP ---------------------------------------

def test_today_comes_with_one_next_action():
    async def scenario():
        async with webapp_client() as (client, _):
            body = await (await call(client, "GET", "/api/today")).json()
            assert "next_action" in body
            action = body["next_action"]
            if action is not None:
                assert action["cta"] and action["text"] and action["target"]
    run(scenario)


def test_the_advice_history_survives_a_reload():
    """Память о показанном лежит в базе, а не в памяти процесса."""
    async def scenario():
        async with webapp_client() as (client, _):
            body = await (await call(client, "GET", "/api/today")).json()
            if body["next_action"] is None:
                return
            code = body["next_action"]["code"]

            from services.gamification import suggestions_today

            async with maker_holder["maker"]() as session:
                assert code in await suggestions_today(
                    session, USER_ID, timezone_name="Europe/Moscow")
    run(scenario)


def test_exactly_three_quests_are_marked_main():
    async def scenario():
        async with webapp_client() as (client, _):
            quests = (await (await call(client, "GET", "/api/today")).json())["game"]["quests"]
            assert quests
            assert sum(1 for q in quests if q.get("main")) == 3
            # Остальные не пропадают — они просто не главные.
            assert sum(1 for q in quests if not q.get("main")) == len(quests) - 3
    run(scenario)


def test_acting_on_the_advice_changes_it():
    """Карточка обязана пересчитаться сразу после действия, а не завтра."""
    async def scenario():
        async with webapp_client() as (client, _):
            first = (await (await call(client, "GET", "/api/today")).json())["next_action"]
            if first is None or first["code"] != "water":
                return          # в этот час советуют не воду — проверять нечего

            await call(client, "POST", "/api/water", json_body={"amount_ml": 2000})
            after = (await (await call(client, "GET", "/api/today")).json())["next_action"]
            assert after is None or after["code"] != "water"
    run(scenario)


def test_reopening_the_screen_does_not_burn_the_advice():
    """Обновление экрана — не показ нового совета.

    Иначе человек, который просто трижды открыл приложение, исчерпал бы
    подсказку, не сделав ничего.
    """
    async def scenario():
        async with webapp_client() as (client, _):
            first = (await (await call(client, "GET", "/api/today")).json())["next_action"]
            if first is None:
                return
            for _ in range(4):
                again = (await (await call(client, "GET", "/api/today")).json())["next_action"]
                assert again is not None, "совет пропал от простых обновлений"
                assert again["code"] == first["code"], "совет менялся сам по себе"
    run(scenario)


# --- Подбор занятия через HTTP ---------------------------------------------

def test_workout_pick_fits_the_time():
    async def scenario():
        async with webapp_client() as (client, _):
            for minutes in (15, 30, 45):
                body = await (await call(client, "POST", "/api/workouts/pick",
                                         json_body={"minutes": minutes})).json()
                assert body["picks"], f"под {minutes} мин ничего"
                for item in body["picks"]:
                    assert item["minutes"] <= minutes * 1.15
                    assert item["why"] and item["title"]
    run(scenario)


def test_five_minutes_returns_short_sets_not_programmes():
    async def scenario():
        async with webapp_client() as (client, _):
            body = await (await call(client, "POST", "/api/workouts/pick",
                                     json_body={"minutes": 5, "quick": True})).json()
            assert body["quick"] is True
            assert body["sets"]
            for item in body["sets"]:
                assert item["minutes"] <= 7
                assert len(item["exercises"]) >= 2
    run(scenario)


def test_workout_pick_needs_a_signature():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "POST", "/api/workouts/pick",
                                  signed=False, json_body={"minutes": 30})
            assert response.status == 401
    run(scenario)


# --- Мой мир через HTTP ----------------------------------------------------

def test_the_world_answers_with_places_and_what_is_next():
    async def scenario():
        async with webapp_client() as (client, _):
            body = await (await call(client, "GET", "/api/world")).json()
            assert body["total"] == 8
            assert len(body["zones"]) == 8
            assert body["title"] and body["subtitle"]
            for zone in body["zones"]:
                assert zone["hint"] and 0 <= zone["stage"] <= zone["stages"]
    run(scenario)


def test_the_world_grows_after_a_real_meal():
    """Мир должен двигаться от того, что человек и так делает."""
    async def scenario():
        async with webapp_client() as (client, _):
            # Открываем «Сегодня»: там закрывается задание и пишется итог дня.
            await call(client, "GET", "/api/today")
            for _ in range(3):
                await call(client, "POST", "/api/meals", json_body={
                    "name": "Овсянка", "weight_g": 250, "calories": 300,
                    "protein_g": 12, "fat_g": 8, "carbs_g": 45, "fiber_g": 6})
            await call(client, "GET", "/api/today")

            body = await (await call(client, "GET", "/api/world")).json()
            garden = next(z for z in body["zones"] if z["code"] == "garden")
            assert garden["open"], "сад не открылся после записей еды"
            assert garden["title"] == "Росток"
    run(scenario)


def test_the_world_needs_a_signature():
    async def scenario():
        async with webapp_client() as (client, _):
            assert (await call(client, "GET", "/api/world", signed=False)).status == 401
    run(scenario)


# --- Гепард через HTTP -----------------------------------------------------

def test_today_comes_with_the_cheetah():
    async def scenario():
        async with webapp_client() as (client, _):
            body = await (await call(client, "GET", "/api/today")).json()
            assert body["cheetah"]["code"]
            assert body["cheetah"]["emoji"] and body["cheetah"]["line"]
    run(scenario)


def test_a_new_place_is_celebrated_once_and_not_every_reload():
    """Радость, повторённая пять раз, перестаёт быть радостью."""
    async def scenario():
        async with webapp_client() as (client, _):
            # В дневнике уже есть запись, значит сад открылся — и это надо
            # заметить ровно один раз.
            await call(client, "GET", "/api/today")
            opened = await (await call(client, "GET", "/api/world")).json()
            assert opened["open"] >= 1, "запись в дневнике не открыла сад"
            assert opened["cheetah"], "открытие места прошло незамеченным"
            assert opened["cheetah"]["code"] == "world_unlock"

            for _ in range(3):
                again = await (await call(client, "GET", "/api/world")).json()
                assert again["cheetah"] is None, "празднует одно и то же дважды"
    run(scenario)


# --- Друзья через HTTP -----------------------------------------------------

def test_friends_answer_carries_nothing_about_the_body():
    """Самая важная проверка PHASE 4: наружу уходит только игровое."""
    async def scenario():
        async with webapp_client() as (client, _):
            from services import friends as svc

            async with maker_holder["maker"]() as session:
                await svc.connect(session, USER_ID, OTHER_ID)

            raw = await (await call(client, "GET", "/api/friends")).text()
            for leak in ("weight", "waist", "hips", "photo", "calorie",
                         "protein", "meal", "measurement", "target_weight"):
                assert leak not in raw.lower(), f"в ответе про друзей есть «{leak}»"

            body = await (await call(client, "GET", "/api/friends")).json()
            assert body["count"] == 1
            for card in body["friends"]:
                assert set(card) == {"user_id", "name", "level", "crystals",
                                     "week", "streak", "me"}
    run(scenario)


def test_a_friend_can_be_removed_and_the_link_renewed():
    async def scenario():
        async with webapp_client() as (client, _):
            from services import friends as svc

            async with maker_holder["maker"]() as session:
                await svc.connect(session, USER_ID, OTHER_ID)

            first = await (await call(client, "GET", "/api/friends")).json()
            assert first["count"] == 1

            renewed = await (await call(client, "POST", "/api/friends",
                                        json_body={"renew": True})).json()
            assert renewed["invite"] != first["invite"] or not first["invite"]

            after = await (await call(client, "POST", "/api/friends",
                                      json_body={"remove": OTHER_ID})).json()
            assert after["count"] == 0
    run(scenario)


def test_you_cannot_remove_someone_elses_friend():
    """Убрать можно только свою связь — чужие трогать нечем."""
    async def scenario():
        async with webapp_client() as (client, _):
            from services import friends as svc

            async with maker_holder["maker"]() as session:
                await svc.connect(session, OTHER_ID, 999)
                session.add(User(id=999, onboarding_completed=True))
                await session.commit()

            await call(client, "POST", "/api/friends", json_body={"remove": 999})

            async with maker_holder["maker"]() as session:
                assert await svc.are_friends(session, OTHER_ID, 999), \
                    "разорвана чужая связь"
    run(scenario)


def test_friends_need_a_signature():
    async def scenario():
        async with webapp_client() as (client, _):
            assert (await call(client, "GET", "/api/friends", signed=False)).status == 401
    run(scenario)
