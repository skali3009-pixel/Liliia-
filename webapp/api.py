"""HTTP-API мини-приложения: читает и пишет ту же базу, что и бот."""

from __future__ import annotations

import logging
from datetime import datetime
from datetime import time as dt_time

from aiohttp import web

import config
from db import get_session
from models import (Meal, MealSourceEnum, ProgressPhoto, ScheduleTypeEnum, Supplement, User,
                    WorkoutTypeEnum)
from services.checkins import save_checkin, today_state
from services.food_vision import FoodAnalysis, FoodRecognitionError
from services.gamification import awards_summary, sync_today
from services.meals import get_today_totals, list_today_meals, save_meal
from services.moments import Moment, analyze_moment, facts as moment_facts
from services.progress import (
    MEASURE_FIELDS,
    add_measurement,
    calorie_points,
    compute_streak,
    list_photos,
    measure_points,
    meal_days,
    photos_dir,
    save_photo,
)
from services.subscriptions import check_access
from services.suggestions import suggest_meals
from services.timeline import day_timeline
from services.supplements import add_supplement, list_due_today, mark
from services.workouts import (
    available_programs,
    styles_for,
    exercise_calories,
    exercise_minutes,
    log_session,
    program_exercises,
    week_summary,
)
from services.water import add_water, today_total_ml, undo_last
from utils.macros import GAP_LABELS, dominant_gap, remaining
from utils.meal_time import MEAL_TYPE_RU, guess_meal_type
from utils.portions import MAX_WEIGHT_G, MIN_WEIGHT_G, scale_nutrition
from utils.timeframe import get_zone, to_local, today_in
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

        # Приложение — часть подписки: без неё показываем экран оплаты, но
        # данные не трогаем, они дождутся возвращения.
        if config.PAYWALL:
            access = await check_access(session, user.id)
            if not access.allowed:
                return web.json_response(
                    {
                        "error": "Подписка закончилась",
                        "need_subscription": True,
                        "access": access.to_dict(),
                        "price_stars": config.SUB_PRICE_STARS,
                    },
                    status=402,
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
        "fiber_g": round(meal.fiber_g or 0),
        "meal_type": MEAL_TYPE_RU.get(meal.meal_type, "") if meal.meal_type else "",
        "time": to_local(meal.logged_at, timezone_name).strftime("%H:%M") if meal.logged_at else "",
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
        state = await today_state(session, user_id, timezone_name=tz)
        timeline = await day_timeline(session, user_id, timezone_name=tz)
        game = await sync_today(
            session,
            user,
            meals_count=len(meals),
            calories=totals.calories,
            fiber_g=totals.fiber_g,
            water_ml=water,
            timezone_name=tz,
            stress_marked=state.stress is not None,
        )

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
                    "fiber_g": user.daily_fiber_g or 0,
                    "water_ml": user.daily_water_ml or 0,
                },
                "totals": {
                    "calories": round(totals.calories),
                    "protein_g": round(totals.protein_g),
                    "fat_g": round(totals.fat_g),
                    "carbs_g": round(totals.carbs_g),
                    "fiber_g": round(totals.fiber_g),
                    "water_ml": water,
                },
                "meals": [_meal_json(m, tz) for m in meals],
                "supplements": [_supplement_json(s) for s in supplements],
                "state": {
                    "energy": state.energy,
                    "focus": state.focus,
                    "mood": state.mood,
                    "stress": state.stress,
                    "sleep_minutes": state.sleep_minutes,
                },
                "timeline": timeline,
                "game": game,
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
                "fiber_g": meal.fiber_g or 0,
            },
            from_weight_g=meal.weight_g,
            to_weight_g=weight,
        )
        meal.weight_g = weight
        meal.calories = scaled["calories"]
        meal.protein_g = scaled["protein_g"]
        meal.fat_g = scaled["fat_g"]
        meal.carbs_g = scaled["carbs_g"]
        meal.fiber_g = scaled["fiber_g"]
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


PERIODS = {"week": 7, "month": 30}

# Загружать гигабайты в дневник ни к чему: обычное фото с телефона меньше.
MAX_PHOTO_BYTES = 10 * 1024 * 1024


async def get_progress(request: web.Request) -> web.Response:
    """Данные для экрана прогресса: график, сводка, стрик, фото."""
    user_id, tz = request["user_id"], request["timezone"]
    days = PERIODS.get(request.query.get("period", "month"), 30)
    metric = request.query.get("metric", "weight")

    async with get_session() as session:
        user = await session.get(User, user_id)

        if metric == "calories":
            points = await calorie_points(session, user_id, days=days, timezone_name=tz)
            title, unit = "Калории", "ккал"
        else:
            points = await measure_points(
                session, user_id, field=metric, days=days, timezone_name=tz
            )
            title, unit = MEASURE_FIELDS.get(metric, MEASURE_FIELDS["weight"])[1:]

        # Вес показываем и за всё время — чтобы видеть путь к цели целиком.
        all_weight = await measure_points(session, user_id, field="weight", days=3650,
                                          timezone_name=tz)
        streak = compute_streak(
            await meal_days(session, user_id, timezone_name=tz), today=today_in(tz)
        )
        photos = await list_photos(session, user_id)
        awards = await awards_summary(session, user_id)

    first_weight = all_weight[0].value if all_weight else user.current_weight_kg
    last_weight = all_weight[-1].value if all_weight else user.current_weight_kg

    return web.json_response(
        {
            "metric": metric,
            "title": title,
            "unit": unit,
            "goal": user.target_weight_kg if metric == "weight" else None,
            "points": [{"day": p.day.isoformat(), "value": p.value} for p in points],
            "summary": {
                "current_weight": last_weight,
                "start_weight": first_weight,
                "target_weight": user.target_weight_kg,
                "changed": round((last_weight or 0) - (first_weight or 0), 1),
                "streak": streak,
            },
            "photos": [
                {"id": photo.id, "date": to_local(photo.taken_at, tz).strftime("%d.%m.%Y")}
                for photo in photos
            ],
            "awards": awards,
        }
    )


async def post_measurement(request: web.Request) -> web.Response:
    body = await request.json()

    values: dict[str, float] = {}
    limits = {"weight_kg": (30, 300), "waist_cm": (30, 200), "hips_cm": (30, 200),
              "chest_cm": (30, 200), "thigh_cm": (20, 120), "arm_cm": (10, 100)}
    for key, (low, high) in limits.items():
        raw = body.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return web.json_response({"error": f"Некорректное значение: {key}"}, status=400)
        if not low <= value <= high:
            return web.json_response(
                {"error": f"Значение вне разумного диапазона ({low}-{high})"}, status=400
            )
        values[key] = value

    if not values:
        return web.json_response({"error": "Заполни хотя бы одно поле"}, status=400)

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        _, norms_updated = await add_measurement(session, user=user, **values)
        norms = {
            "calories": user.daily_calories,
            "protein_g": user.daily_protein_g,
            "fat_g": user.daily_fat_g,
            "carbs_g": user.daily_carbs_g,
            "fiber_g": user.daily_fiber_g,
            "water_ml": user.daily_water_ml,
        }

    return web.json_response({"ok": True, "norms_updated": norms_updated, "norms": norms})


async def post_photo(request: web.Request) -> web.Response:
    """Фото прогресса загружается прямо из приложения."""
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "photo":
        return web.json_response({"error": "Нет файла"}, status=400)

    content = bytearray()
    while chunk := await field.read_chunk():
        content.extend(chunk)
        if len(content) > MAX_PHOTO_BYTES:
            return web.json_response({"error": "Фото слишком большое (максимум 10 МБ)"}, status=400)

    if not content:
        return web.json_response({"error": "Пустой файл"}, status=400)

    async with get_session() as session:
        photo = await save_photo(session, user_id=request["user_id"], content=bytes(content))
    return web.json_response({"id": photo.id})


async def get_photo(request: web.Request) -> web.Response:
    photo_id = int(request.match_info["photo_id"])
    async with get_session() as session:
        photo = await session.get(ProgressPhoto, photo_id)
        if photo is None or photo.user_id != request["user_id"] or not photo.file_name:
            return web.json_response({"error": "Фото не найдено"}, status=404)
        path = photos_dir(photo.user_id) / photo.file_name

    if not path.exists():
        return web.json_response({"error": "Файл потерялся"}, status=404)
    return web.FileResponse(path)


async def delete_photo(request: web.Request) -> web.Response:
    photo_id = int(request.match_info["photo_id"])
    async with get_session() as session:
        photo = await session.get(ProgressPhoto, photo_id)
        if photo is None or photo.user_id != request["user_id"]:
            return web.json_response({"error": "Фото не найдено"}, status=404)
        if photo.file_name:
            (photos_dir(photo.user_id) / photo.file_name).unlink(missing_ok=True)
        await session.delete(photo)
        await session.commit()
    return web.json_response({"ok": True})


async def get_workouts(request: web.Request) -> web.Response:
    """Программы под выбранные место и уровень плюс упражнения выбранной."""
    user_id, tz = request["user_id"], request["timezone"]
    category = request.query.get("category", "body")
    style = request.query.get("style") or None
    program_code = request.query.get("program")

    async with get_session() as session:
        user = await session.get(User, user_id)
        weight = user.current_weight_kg or 70

        programs = available_programs(category=category, style=style)
        # Если стиль не подошёл ни к одной программе — показываем всё направление.
        if not programs:
            programs = available_programs(category=category)
        chosen = program_code or (programs[0].code if programs else None)

        exercises = await program_exercises(session, chosen) if chosen else []
        # Отдельный список кардио нужен только в разделе тела.
        cardio = await program_exercises(session, "cardio") if category == "body" else []
        summary = await week_summary(session, user_id, timezone_name=tz)

    def exercise_json(workout) -> dict:
        return {
            "id": workout.id,
            "name": workout.name,
            "muscle": workout.muscle_group or "",
            "sets": workout.sets,
            "reps": workout.reps,
            "rest_seconds": workout.rest_seconds,
            "seconds_per_set": (
                int(workout.duration_minutes)
                if workout.duration_minutes and workout.workout_type != WorkoutTypeEnum.CARDIO
                else None
            ),
            "minutes": round(exercise_minutes(workout)),
            "calories": round(exercise_calories(workout, weight)),
            "demo_url": workout.demo_url,
            "is_cardio": workout.workout_type == WorkoutTypeEnum.CARDIO,
        }

    from seed.workout_programs import CATEGORIES, CATEGORIES_WITH_CALORIES

    chosen_program = next((p for p in programs if p.code == chosen), None)

    return web.json_response(
        {
            "categories": [{"code": code, "label": label} for code, label in CATEGORIES],
            "styles": [{"code": code, "label": label} for code, label in styles_for(category)],
            "category": category,
            "style": style,
            "show_calories": category in CATEGORIES_WITH_CALORIES,
            "note": chosen_program.note if chosen_program else None,
            "programs": [
                {
                    "code": p.code,
                    "title": p.title,
                    "subtitle": p.subtitle,
                    "exercise_count": p.exercise_count,
                }
                for p in programs
            ],
            "selected": chosen,
            "exercises": [exercise_json(w) for w in exercises],
            "cardio": [exercise_json(w) for w in cardio],
            "week": summary,
        }
    )


async def post_workout_log(request: web.Request) -> web.Response:
    """Записать выполненные упражнения и посчитать расход."""
    body = await request.json()
    raw_ids = body.get("exercise_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return web.json_response({"error": "Не отмечено ни одного упражнения"}, status=400)

    try:
        exercise_ids = [int(value) for value in raw_ids][:50]
    except (TypeError, ValueError):
        return web.json_response({"error": "Некорректный список упражнений"}, status=400)

    minutes = None
    if body.get("minutes") not in (None, ""):
        try:
            minutes = float(body["minutes"])
        except (TypeError, ValueError):
            return web.json_response({"error": "Некорректное время"}, status=400)
        if not 1 <= minutes <= 300:
            return web.json_response({"error": "Время от 1 до 300 минут"}, status=400)

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        count, total_minutes, calories = await log_session(
            session,
            user_id=user.id,
            weight_kg=user.current_weight_kg or 70,
            exercise_ids=exercise_ids,
            minutes=minutes,
        )
        summary = await week_summary(session, user.id, timezone_name=request["timezone"])

    return web.json_response(
        {"logged": count, "minutes": total_minutes, "calories": calories, "week": summary}
    )


async def post_suggestions(request: web.Request) -> web.Response:
    """Три варианта еды под остаток нормы — подбирает Claude."""
    user_id, tz = request["user_id"], request["timezone"]

    async with get_session() as session:
        user = await session.get(User, user_id)
        totals = await get_today_totals(session, user_id, timezone_name=tz)
        norms = {
            "calories": user.daily_calories or 0,
            "protein_g": user.daily_protein_g or 0,
            "fat_g": user.daily_fat_g or 0,
            "carbs_g": user.daily_carbs_g or 0,
            "fiber_g": user.daily_fiber_g or 0,
        }

    left = remaining(
        {"calories": totals.calories, "protein_g": totals.protein_g,
         "fat_g": totals.fat_g, "carbs_g": totals.carbs_g, "fiber_g": totals.fiber_g},
        norms,
    )

    try:
        suggestions = await suggest_meals(user, left, norms)
    except FoodRecognitionError as e:
        return web.json_response({"error": str(e)}, status=503)

    gap = dominant_gap(left, norms)
    return web.json_response(
        {
            "remaining": {
                "calories": left.calories, "protein_g": left.protein_g,
                "fat_g": left.fat_g, "carbs_g": left.carbs_g, "fiber_g": left.fiber_g,
            },
            "gap": GAP_LABELS.get(gap) if gap else None,
            "suggestions": [item.to_dict() for item in suggestions],
        }
    )


async def post_meal(request: web.Request) -> web.Response:
    """Записать блюдо целиком — например, выбранное из рекомендаций."""
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return web.json_response({"error": "Нужно название"}, status=400)

    def number(key: str) -> float:
        try:
            return max(float(body.get(key, 0)), 0)
        except (TypeError, ValueError):
            return 0.0

    analysis = FoodAnalysis(
        name=name[:60],
        weight_g=number("weight_g"),
        calories=number("calories"),
        protein_g=number("protein_g"),
        fat_g=number("fat_g"),
        carbs_g=number("carbs_g"),
        fiber_g=number("fiber_g"),
        confidence="medium",
        comment="",
    )

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        await save_meal(
            session,
            user_id=user.id,
            analysis=analysis,
            source=MealSourceEnum.TEXT,
            meal_type=guess_meal_type(datetime.now(get_zone(request["timezone"]))),
        )
        totals = await get_today_totals(session, user.id, timezone_name=request["timezone"])

    return web.json_response({"ok": True, "calories_today": round(totals.calories)})


async def post_moment(request: web.Request) -> web.Response:
    """Свободная фраза → распознанные факты. Ничего пока не сохраняем."""
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text:
        return web.json_response({"error": "Расскажи, что происходит"}, status=400)
    if len(text) > 500:
        return web.json_response({"error": "Слишком длинно — уложись в 500 символов"}, status=400)

    now = datetime.now(get_zone(request["timezone"]))
    try:
        moment = await analyze_moment(text, now=now)
    except FoodRecognitionError as e:
        return web.json_response({"error": str(e)}, status=503)

    if moment.is_empty:
        return web.json_response(
            {"error": "Не нашла здесь ни еды, ни самочувствия. Скажи чуть подробнее."},
            status=422,
        )

    return web.json_response({
        "moment": moment.to_dict(),
        "facts": moment_facts(moment),
        "summary": moment.summary,
    })


def _moment_time(raw: str, timezone_name: str) -> datetime:
    """Время момента: то, что человек поправил, иначе — сейчас.

    Дата всегда сегодняшняя: моменты записываются день в день.
    """
    now = datetime.now(get_zone(timezone_name))
    try:
        hours, minutes = (int(part) for part in str(raw).split(":", 1))
    except (TypeError, ValueError):
        return now
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return now
    return now.replace(hour=hours, minute=minutes, second=0, microsecond=0)


async def confirm_moment(request: web.Request) -> web.Response:
    """Сохранить подтверждённый момент: еду, состояние или и то, и другое."""
    body = await request.json()
    try:
        moment = Moment.from_dict(body["moment"])
    except (KeyError, TypeError, ValueError):
        return web.json_response({"error": "Момент устарел, повтори ввод"}, status=400)

    user_id, tz = request["user_id"], request["timezone"]
    saved = []
    at = _moment_time(moment.at, tz)

    async with get_session() as session:
        if moment.food:
            await save_meal(
                session,
                user_id=user_id,
                analysis=moment.food,
                source=MealSourceEnum.TEXT,
                meal_type=guess_meal_type(at),
                logged_at=at,
            )
            saved.append("еда")
        if moment.has_state:
            await save_checkin(
                session,
                user_id=user_id,
                energy=moment.energy,
                focus=moment.focus,
                mood=moment.mood,
                stress=moment.stress,
                sleep_minutes=moment.sleep_minutes,
                note=moment.text,
                logged_at=at,
            )
            saved.append("самочувствие")

    return web.json_response({"saved": saved})


async def recount_moment(request: web.Request) -> web.Response:
    """Пересобрать факты после правки: список строит сервер, чтобы правила
    показа и пересчёта жили в одном месте."""
    body = await request.json()
    try:
        moment = Moment.from_dict(body["moment"])
    except (KeyError, TypeError, ValueError):
        return web.json_response({"error": "Момент устарел, повтори ввод"}, status=400)
    return web.json_response({"moment": moment.to_dict(), "facts": moment_facts(moment)})


async def post_checkin(request: web.Request) -> web.Response:
    """Отметить состояние кнопками, без разбора текста."""
    body = await request.json()

    def score(key: str) -> int | None:
        raw = body.get(key)
        if raw in (None, ""):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if 1 <= value <= 10 else None

    def choice(key: str, allowed: list[str]) -> str | None:
        value = str(body.get(key, "")).strip().lower()
        return value if value in allowed and value else None

    from services.moments import MOODS, STRESS_LEVELS

    energy, focus = score("energy"), score("focus")
    mood, stress = choice("mood", MOODS), choice("stress", STRESS_LEVELS)
    if not any((energy, focus, mood, stress)):
        return web.json_response({"error": "Нечего сохранять"}, status=400)

    async with get_session() as session:
        await save_checkin(
            session, user_id=request["user_id"], energy=energy, focus=focus,
            mood=mood, stress=stress,
        )
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
    app.router.add_get("/api/progress", get_progress)
    app.router.add_post("/api/measurements", post_measurement)
    app.router.add_post("/api/photos", post_photo)
    app.router.add_get("/api/photos/{photo_id}", get_photo)
    app.router.add_delete("/api/photos/{photo_id}", delete_photo)
    app.router.add_get("/api/workouts", get_workouts)
    app.router.add_post("/api/workouts/log", post_workout_log)
    app.router.add_post("/api/suggestions", post_suggestions)
    app.router.add_post("/api/meals", post_meal)
    app.router.add_post("/api/moment", post_moment)
    app.router.add_post("/api/moment/confirm", confirm_moment)
    app.router.add_post("/api/moment/facts", recount_moment)
    app.router.add_post("/api/checkin", post_checkin)
