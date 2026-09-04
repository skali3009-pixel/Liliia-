"""HTTP-API мини-приложения: читает и пишет ту же базу, что и бот."""

from __future__ import annotations

import logging
from datetime import time as dt_time

from aiohttp import web

import config
from db import get_session
from models import Meal, ScheduleTypeEnum, Supplement, User
from services.meals import get_today_totals, list_today_meals
from services.supplements import add_supplement, list_due_today, mark
from services.water import add_water, today_total_ml, undo_last
from utils.meal_time import MEAL_TYPE_RU
from utils.portions import MAX_WEIGHT_G, MIN_WEIGHT_G, scale_nutrition
from utils.timeframe import get_zone
from webapp.auth import AuthError, verify_init_data

logger = logging.getLogger(__name__)

INIT_DATA_HEADER = "X-Telegram-Init-Data"


@web.middleware
async def error_middleware(request: web.Request, handler):
    """Любая необработанная ошибка — в лог с трассировкой, пользователю —
    человеческий текст вместо голого «500»."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Ошибка в %s %s", request.method, request.path)
        return web.json_response(
            {"error": "Что-то сломалось на сервере. Загляни в логи бота."}, status=500
        )


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Пускаем к данным только с действительной подписью Telegram."""
    if not request.path.startswith("/api/"):
        return await handler(request)

    try:
        tg_user = verify_init_data(request.headers.get(INIT_DATA_HEADER, ""), config.BOT_TOKEN)
    except AuthError as e:
        return web.json_response({"error": str(e)}, status=401)

    async with get_session() as session:
        user = await session.get(User, tg_user.id)
        if user is None or not user.onboarding_completed:
            return web.json_response(
                {"error": "Профиль не настроен", "need_onboarding": True}, status=403
            )
        request["user_id"] = user.id
        request["timezone"] = user.timezone

    return await handler(request)


def _meal_json(meal: Meal, timezone_name: str) -> dict:
    zone = get_zone(timezone_name)
    return {
        "id": meal.id,
        "name": meal.name,
        "weight_g": round(meal.weight_g or 0),
        "calories": round(meal.calories),
        "protein_g": round(meal.protein_g),
        "fat_g": round(meal.fat_g),
        "carbs_g": round(meal.carbs_g),
        "meal_type": MEAL_TYPE_RU.get(meal.meal_type, "") if meal.meal_type else "",
        "time": meal.logged_at.astimezone(zone).strftime("%H:%M") if meal.logged_at else "",
        "source": meal.source.value if meal.source else "text",
    }


def _supplement_json(item) -> dict:
    supplement = item.supplement
    return {
        "id": supplement.id,
        "name": supplement.name,
        "dose": supplement.dose or "",
        "schedule": item.schedule_label,
        "taken": item.taken,
        "skipped": item.skipped,
    }


async def get_today(request: web.Request) -> web.Response:
    """Всё, что нужно главному экрану, одним запросом."""
    user_id, tz = request["user_id"], request["timezone"]

    async with get_session() as session:
        user = await session.get(User, user_id)
        totals = await get_today_totals(session, user_id, timezone_name=tz)
        meals = await list_today_meals(session, user_id, timezone_name=tz)
        water = await today_total_ml(session, user_id, timezone_name=tz)
        supplements = await list_due_today(session, user_id, timezone_name=tz)

        return web.json_response(
            {
                "profile": {
                    "name": (user.full_name or "").split(" ")[0],
                    "goal": user.goal.value if user.goal else None,
                    "weight_kg": user.current_weight_kg,
                    "target_weight_kg": user.target_weight_kg,
                },
                "norms": {
                    "calories": user.daily_calories or 0,
                    "protein_g": user.daily_protein_g or 0,
                    "fat_g": user.daily_fat_g or 0,
                    "carbs_g": user.daily_carbs_g or 0,
                    "water_ml": user.daily_water_ml or 0,
                },
                "totals": {
                    "calories": round(totals.calories),
                    "protein_g": round(totals.protein_g),
                    "fat_g": round(totals.fat_g),
                    "carbs_g": round(totals.carbs_g),
                    "water_ml": water,
                },
                "meals": [_meal_json(m, tz) for m in meals],
                "supplements": [_supplement_json(s) for s in supplements],
            }
        )


async def post_water(request: web.Request) -> web.Response:
    body = await request.json()
    amount = int(body.get("amount_ml", 0))
    if not 10 <= amount <= 3000:
        return web.json_response({"error": "Некорректный объём"}, status=400)

    async with get_session() as session:
        await add_water(session, user_id=request["user_id"], amount_ml=amount)
        total = await today_total_ml(session, request["user_id"], timezone_name=request["timezone"])
    return web.json_response({"water_ml": total})


async def undo_water(request: web.Request) -> web.Response:
    async with get_session() as session:
        removed = await undo_last(session, request["user_id"], timezone_name=request["timezone"])
        total = await today_total_ml(session, request["user_id"], timezone_name=request["timezone"])
    return web.json_response({"water_ml": total, "removed_ml": removed})


async def update_meal(request: web.Request) -> web.Response:
    """Поправить вес порции — КБЖУ пересчитываются пропорционально."""
    meal_id = int(request.match_info["meal_id"])
    body = await request.json()
    weight = float(body.get("weight_g", 0))
    if not MIN_WEIGHT_G <= weight <= MAX_WEIGHT_G:
        return web.json_response({"error": "Некорректный вес"}, status=400)

    async with get_session() as session:
        meal = await session.get(Meal, meal_id)
        if meal is None or meal.user_id != request["user_id"]:
            return web.json_response({"error": "Запись не найдена"}, status=404)
        if not meal.weight_g:
            return web.json_response({"error": "У записи не указан вес"}, status=400)

        scaled = scale_nutrition(
            {
                "calories": meal.calories,
                "protein_g": meal.protein_g,
                "fat_g": meal.fat_g,
                "carbs_g": meal.carbs_g,
            },
            from_weight_g=meal.weight_g,
            to_weight_g=weight,
        )
        meal.weight_g = weight
        meal.calories = scaled["calories"]
        meal.protein_g = scaled["protein_g"]
        meal.fat_g = scaled["fat_g"]
        meal.carbs_g = scaled["carbs_g"]
        await session.commit()
        return web.json_response(_meal_json(meal, request["timezone"]))


async def delete_meal_entry(request: web.Request) -> web.Response:
    meal_id = int(request.match_info["meal_id"])
    async with get_session() as session:
        meal = await session.get(Meal, meal_id)
        if meal is None or meal.user_id != request["user_id"]:
            return web.json_response({"error": "Запись не найдена"}, status=404)
        await session.delete(meal)
        await session.commit()
    return web.json_response({"ok": True})


async def post_supplement(request: web.Request) -> web.Response:
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return web.json_response({"error": "Нужно название"}, status=400)

    schedule_raw = str(body.get("schedule_type", "daily"))
    try:
        schedule_type = ScheduleTypeEnum(schedule_raw)
    except ValueError:
        return web.json_response({"error": "Неизвестное расписание"}, status=400)

    reminder = None
    if raw_time := str(body.get("reminder_time", "")).strip():
        try:
            hours, minutes = (int(part) for part in raw_time.split(":", 1))
            reminder = dt_time(hours, minutes)
        except (ValueError, TypeError):
            return web.json_response({"error": "Некорректное время"}, status=400)

    async with get_session() as session:
        supplement = await add_supplement(
            session,
            user_id=request["user_id"],
            name=name,
            dose=str(body.get("dose", "")),
            schedule_type=schedule_type,
            weekdays=str(body.get("weekdays", "")) or None,
            interval_days=int(body["interval_days"]) if body.get("interval_days") else None,
            reminder_time=reminder,
        )
    return web.json_response({"id": supplement.id})


async def mark_supplement(request: web.Request) -> web.Response:
    supplement_id = int(request.match_info["supplement_id"])
    body = await request.json() if request.can_read_body else {}
    try:
        async with get_session() as session:
            await mark(
                session,
                user_id=request["user_id"],
                supplement_id=supplement_id,
                skipped=bool(body.get("skipped")),
                timezone_name=request["timezone"],
            )
    except ValueError:
        return web.json_response({"error": "Препарат не найден"}, status=404)
    return web.json_response({"ok": True})


async def delete_supplement(request: web.Request) -> web.Response:
    supplement_id = int(request.match_info["supplement_id"])
    async with get_session() as session:
        supplement = await session.get(Supplement, supplement_id)
        if supplement is None or supplement.user_id != request["user_id"]:
            return web.json_response({"error": "Препарат не найден"}, status=404)
        supplement.is_active = False
        await session.commit()
    return web.json_response({"ok": True})


def add_routes(app: web.Application) -> None:
    app.router.add_get("/api/today", get_today)
    app.router.add_post("/api/water", post_water)
    app.router.add_post("/api/water/undo", undo_water)
    app.router.add_patch("/api/meals/{meal_id}", update_meal)
    app.router.add_delete("/api/meals/{meal_id}", delete_meal_entry)
    app.router.add_post("/api/supplements", post_supplement)
    app.router.add_post("/api/supplements/{supplement_id}/mark", mark_supplement)
    app.router.add_delete("/api/supplements/{supplement_id}", delete_supplement)
