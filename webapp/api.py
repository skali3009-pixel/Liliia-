"""HTTP-API мини-приложения: читает и пишет ту же базу, что и бот."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from datetime import time as dt_time

from aiohttp import web

import config
from db import get_session
from models import (GenderEnum, Meal, MealSourceEnum, Prep, PrepComponent,
                    Product, ProgressPhoto,
                    ScheduleTypeEnum, Supplement, User, WorkoutTypeEnum)
from services import events as event_service
from services import cycle
from services import notifications
from services import preps as prep_service
from services.checkins import save_checkin, today_state
from services.preps import expiring_names
from services.workouts import recent_program_codes
from services.favorites import frequent_meals
from services.food_vision import FoodAnalysis, FoodRecognitionError
from services import usage
from services.gamification import awards_summary, sync_today
from services import context
from services import turn as turn_service
from services.meals import get_today_totals, list_today_meals, save_meal
from services.menu import board as menu_board
from services.moments import Moment, analyze_moment, facts as moment_facts
from services.export import build_export
from services.profile import (
    ACTIVITY_RU,
    DIET_RU,
    GENDER_RU,
    GOAL_RU,
    MAX_AGE,
    MAX_HEIGHT_CM,
    MAX_TARGET_KG,
    MIN_AGE,
    MIN_HEIGHT_CM,
    MIN_TARGET_KG,
    ProfileError,
    apply as apply_profile,
)
from services.progress import (
    MEASURE_FIELDS,
    add_measurement,
    calorie_points,
    compute_streak,
    latest_measures,
    list_photos,
    measure_points,
    meal_days,
    photos_dir,
    save_photo,
)
from services.subscriptions import check_access
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
from utils.body import (build_insights, build_silhouette, goal_silhouette,
                        warp_factors, zones)
from utils.daily_line import daily_line
from utils.disk import usage as disk_usage
from utils import images
from utils.macros import GAP_LABELS, dominant_gap, remaining
from utils.meal_time import MEAL_TYPE_RU, guess_meal_type
from utils.portions import MAX_WEIGHT_G, MIN_WEIGHT_G, scale_nutrition
from utils.timeframe import (DEFAULT_TIMEZONE, get_zone, is_known_zone,
                            to_local, today_in)
from webapp.auth import AuthError, verify_init_data

logger = logging.getLogger(__name__)

INIT_DATA_HEADER = "X-Telegram-Init-Data"
TIMEZONE_HEADER = "X-Timezone"


@web.middleware
async def error_middleware(request: web.Request, handler):
    """Любая необработанная ошибка — в лог с трассировкой, пользователю —
    человеческий текст вместо голого «500»."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as error:
        # Владелец узнаёт о поломке сразу, а не из логов и не от человека.
        from services import crashes

        await crashes.report(
            request.app.get(BOT_KEY), error,
            where=f"приложение {request.method} {request.path}",
            user_id=request.get("user_id"),
        )
        return web.json_response(
            {"error": "Что-то сломалось на нашей стороне. Я уже сообщил хозяйке "
                      "бота — твои записи целы."},
            status=500,
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

        # Часовой пояс приложение сообщает само — его знает браузер. Иначе
        # он навсегда остаётся московским, и у человека из другого пояса
        # день начинается и заканчивается не тогда, когда у него на часах:
        # утренняя еда уезжает во вчера, а норма обнуляется среди дня.
        reported = request.headers.get(TIMEZONE_HEADER, "").strip()
        if reported != user.timezone and is_known_zone(reported):
            logger.info("Часовой пояс %s: %s → %s", user.id, user.timezone, reported)
            user.timezone = reported
            await session.commit()

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
        # Отметка «человек сам открыл приложение». По ней движок уведомлений
        # молчит: подсказка вдогонку открытому экрану только раздражает.
        # Заодно это ответ на недавнее сообщение — слабее нажатой кнопки,
        # но тоже ответ, и без него непонятно, работает ли текст вообще.
        if user is not None:
            user.last_app_open = datetime.now(timezone.utc)
            await notifications.note_app_open(session, user_id)
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

        # Что сейчас полезнее всего сделать. Считается после игрового
        # пересчёта, чтобы совет учитывал уже закрытые задания.
        parts = dict(totals=totals, water=water, meals=len(meals), state=state,
                     game=game, days_since_measure=game.get("days_since_measure"),
                     preps=await expiring_names(session, user_id, timezone_name=tz))
        action = await turn_service.next_action(session, user, tz, **parts)
        main_codes = context.main_quest_codes(
            turn_service.day_context(user, tz, suggested=(), **parts), game["quests"])
        for quest in game["quests"]:
            quest["main"] = quest["code"] in main_codes

        # Находка случается только после того, как человек что-то закрыл.
        found = await event_service.surprise(
            session, user_id, closed_now=bool(game.get("just_completed")),
            timezone_name=tz)
        if found:
            game["surprise"] = found

        # Гепард не советует — он реагирует. Считается там же, где для чата:
        # одно правило на оба места.
        cheetah = await turn_service.cheetah_for(
            session, user, tz, game=game, state=state, water=water)

        return web.json_response(
            {
                "cheetah": cheetah.to_dict(),
                "next_action": action.to_dict() if action else None,
                "profile": {
                    "name": (user.full_name or "").split(" ")[0],
                    "goal": user.goal.value if user.goal else None,
                    "weight_kg": user.current_weight_kg,
                    "target_weight_kg": user.target_weight_kg,
                    # Фраза дня: под цель, одна на весь день.
                    "line": daily_line(
                        goal=user.goal.value if user.goal else None,
                        user_id=user.id,
                        day=today_in(tz),
                    ),
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
                "frequent": [item.to_dict() for item in
                             await frequent_meals(session, user_id, timezone_name=tz)],
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

# Бот в приложении нужен ровно для одного: сообщить владельцу о поломке.
# Отдельный ключ вместо строки — так требует aiohttp.
BOT_KEY: web.AppKey = web.AppKey("bot", object)


# Замеры в базе названы по-своему («chest», «hips»), а фигура рисуется по
# анатомическим именам — держим перевод в одном месте.
BODY_KEYS = {"chest": "bust", "hips": "hip", "waist": "waist", "thigh": "thigh", "arm": "arm"}


def _body_block(user: User, measures: dict[str, float], *, weight_kg: float | None) -> dict:
    """Данные для фигуры на экране прогресса: силуэт, ориентир, зоны, выводы."""
    height_cm = user.height_cm or 0
    weight = weight_kg or user.current_weight_kg or 0
    body_measures = {
        body_key: measures[measure_key]
        for measure_key, body_key in BODY_KEYS.items()
        if measures.get(measure_key)
    }

    now, estimated = build_silhouette(
        measures=body_measures, height_cm=height_cm, weight_kg=weight
    )
    goal = goal_silhouette(
        now,
        weight_kg=weight,
        target_weight_kg=user.target_weight_kg or 0,
        height_cm=height_cm,
        estimated=estimated,
    )

    return {
        "now": now.to_dict(),
        "goal": goal.to_dict() if goal else None,
        # Насколько растянуть рисунок фигуры под это тело и под цель.
        "warp": warp_factors(now, height_cm=height_cm),
        "goal_warp": warp_factors(goal, height_cm=height_cm) if goal else None,
        "estimated": estimated,
        "zones": zones(body_measures),
        "insights": [
            item.to_dict()
            for item in build_insights(
                weight_kg=weight,
                target_weight_kg=user.target_weight_kg,
                height_cm=height_cm,
                waist_cm=body_measures.get("waist"),
                protein_g=user.daily_protein_g,
                water_ml=user.daily_water_ml,
            )
        ],
    }


def _usual_weight(points, today) -> float | None:
    """Обычный вес человека: середина замеров от десяти до тридцати пяти
    дней назад.

    Не среднее за месяц: в него попадёт и сегодняшний день, а он-то и
    проверяется. И не один замер: весы врут на полкило от времени суток.
    Середина ряда устойчива и к тому, и к другому.
    """
    window = [p.value for p in points
              if p.value is not None and 10 <= (today - p.day).days <= 35]
    if not window:
        return None
    window.sort()
    middle = len(window) // 2
    if len(window) % 2:
        return window[middle]
    return round((window[middle - 1] + window[middle]) / 2, 1)


def _cycle_shown(user: User | None) -> bool:
    """Календарь — только тем, кому он нужен, и кто его не выключил.

    Мужчине он бессмыслен, а женщине может быть просто не нужен: показывать
    его всем подряд — значит навязывать разговор о теле, которого человек
    не начинал.
    """
    return bool(user and user.gender == GenderEnum.FEMALE and user.cycle_enabled)


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
        measures = await latest_measures(session, user_id)
        cycle_state = (await cycle.state(session, user_id, today_in(tz))
                       if _cycle_shown(user) else None)

    first_weight = all_weight[0].value if all_weight else user.current_weight_kg
    last_weight = all_weight[-1].value if all_weight else user.current_weight_kg

    cycle_json = None
    if cycle_state is not None:
        cycle_json = cycle_state.to_dict()
        # Тот самый вывод, ради которого календарь и нужен: объяснить
        # прибавку перед месячными в ту минуту, когда человек смотрит
        # на график и решает, что всё зря.
        cycle_json["weight_note"] = cycle.weight_note(
            cycle_state, latest_kg=last_weight,
            usual_kg=_usual_weight(all_weight, today_in(tz)),
        )

    return web.json_response(
        {
            "metric": metric,
            "title": title,
            "unit": unit,
            "goal": user.target_weight_kg if metric == "weight" else None,
            "cycle": cycle_json,
            "points": [{"day": p.day.isoformat(), "value": p.value} for p in points],
            "summary": {
                "current_weight": last_weight,
                "start_weight": first_weight,
                "target_weight": user.target_weight_kg,
                "changed": round((last_weight or 0) - (first_weight or 0), 1),
                "streak": streak,
            },
            "body": _body_block(user, measures, weight_kg=last_weight),
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
        arrival = await _arrival(session, user)

    return web.json_response({"ok": True, "norms_updated": norms_updated,
                              "norms": norms, "arrival": arrival})


async def _arrival(session, user: User) -> dict | None:
    """Дошёл ли человек до цели — и говорили ли мы ему об этом раньше.

    Один раз: поздравление на каждом следующем взвешивании превращается в
    шум, а вопрос про поддержание — в назойливость.
    """
    from sqlalchemy import select as _select

    from models import Achievement, BodyMeasurement
    from services import goal as goal_service

    if not goal_service.reached(user, user.current_weight_kg):
        return None

    told = (await session.execute(
        _select(Achievement.id).where(Achievement.user_id == user.id,
                                      Achievement.code == "goal_reached")
    )).first()
    if told is not None:
        return None

    started = (await session.execute(
        _select(BodyMeasurement.weight_kg)
        .where(BodyMeasurement.user_id == user.id, BodyMeasurement.weight_kg.is_not(None))
        .order_by(BodyMeasurement.measured_at).limit(1)
    )).scalar_one_or_none()

    return {
        "text": goal_service.render(goal_service.Arrival(
            weight_kg=user.current_weight_kg, target_kg=user.target_weight_kg,
            started_kg=started)),
        "can_switch": user.goal is not None and user.goal.value != "maintain",
    }


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

    # Место на диске кончается раньше всего именно из-за фотографий, а вместе
    # с местом встаёт и запись дневника. Поэтому фото отключаются первыми.
    disk = disk_usage()
    if disk.full:
        logger.warning("Диск заполнен на %s%% — приём фото остановлен", disk.percent)
        return web.json_response(
            {"error": "На сервере кончается место — фото пока не принимаются"}, status=507
        )

    # Снимок с телефона весит 3–5 МБ, а для сравнения «до/после» на экране
    # хватает 1600 пикселей по длинной стороне — это в разы меньше.
    shrunk = images.for_progress(bytes(content))
    async with get_session() as session:
        photo = await save_photo(session, user_id=request["user_id"], content=shrunk)
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
        # Занятия («я бегала сорок минут») нужны в любом направлении, а
        # не только в «Теле»: человек, который пришёл за йогой, точно так
        # же ходит пешком и плавает. Раньше список был виден лишь в одном
        # разделе — и его просто не находили.
        cardio = await program_exercises(session, "cardio")
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
            # Предупреждение перед личной темой. Приходит отдельным полем,
            # чтобы приложение показало его вместо упражнений, а не под ними.
            "warning": chosen_program.warning if chosen_program else None,
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



# --- Профиль: то же, что кнопками в чате, но не выходя из приложения ---

def _options(mapping: dict[str, str]) -> list[dict]:
    """Варианты выбора для приложения: код — в базу, подпись — человеку."""
    return [{"code": code, "label": label} for code, label in mapping.items()]


from services.steps import GOAL_CHOICES as _STEP_CHOICES
from services.steps import goal_for as _steps_goal


NOTIFY_LABELS = (
    ("turn", "Твой ход"),
    ("meal", "Еда"),
    ("water", "Вода"),
    ("movement", "Движение"),
    ("world", "Мир и события"),
    ("evening", "Итоги дня"),
    ("achievement", "Достижения"),
)

PACE_LABELS = (
    ("minimal", "Минимум"),
    ("balanced", "Сбалансированно"),
    ("active", "Активно"),
)


def _notify_json(prefs) -> dict:
    return {
        "kinds": [{"code": code, "label": label, "on": prefs.allows(code)}
                  for code, label in NOTIFY_LABELS],
        "pace": prefs.pace,
        "paces": [{"code": code, "label": label} for code, label in PACE_LABELS],
        "quiet_from": prefs.quiet_from,
        "quiet_to": prefs.quiet_to,
    }


def _profile_json(user: User, prefs=None) -> dict:
    return {
        "notifications": _notify_json(prefs) if prefs is not None else None,
        "profile": {
            "name": (user.full_name or "").split(" ")[0],
            "gender": user.gender.value if user.gender else None,
            "gender_label": GENDER_RU.get(user.gender.value) if user.gender else None,
            "age": user.age,
            "height_cm": user.height_cm,
            "weight_kg": user.current_weight_kg,
            "target_weight_kg": user.target_weight_kg,
            "goal": user.goal.value if user.goal else None,
            "activity": user.activity_level.value if user.activity_level else None,
            "diet": user.diet_type.value if user.diet_type else None,
            "allergies": user.allergies or "",
            "reminders": bool(user.reminders_enabled),
            "cycle": bool(user.cycle_enabled),
            "steps_goal": user.daily_steps or 0,
        },
        "norms": {
            "calories": user.daily_calories or 0,
            "protein_g": user.daily_protein_g or 0,
            "fat_g": user.daily_fat_g or 0,
            "carbs_g": user.daily_carbs_g or 0,
            "fiber_g": user.daily_fiber_g or 0,
            "water_ml": user.daily_water_ml or 0,
        },
        "steps": {
            "goal": _steps_goal(user),
            "choices": list(_STEP_CHOICES),
        },
        "options": {
            "goal": _options(GOAL_RU),
            "activity": _options(ACTIVITY_RU),
            "diet": _options(DIET_RU),
        },
        # Границы приходят с сервера, чтобы поле не принимало то, что API
        # всё равно отвергнет.
        "limits": {
            "age": [MIN_AGE, MAX_AGE],
            "height": [MIN_HEIGHT_CM, MAX_HEIGHT_CM],
            "target_weight": [MIN_TARGET_KG, MAX_TARGET_KG],
        },
    }


async def get_profile(request: web.Request) -> web.Response:
    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        prefs = await notifications.prefs_for(session, request["user_id"])
    return web.json_response(_profile_json(user, prefs))


async def patch_profile(request: web.Request) -> web.Response:
    """Правка профиля. Вес не трогаем: он меняется замером, а не настройкой."""
    changes = await request.json()
    if not isinstance(changes, dict) or not changes:
        return web.json_response({"error": "Нечего менять"}, status=400)

    # Настройки уведомлений приходят тем же запросом, но живут в своей
    # таблице: смешивать их с анкетой значило бы пересчитывать нормы при
    # каждом снятии галочки.
    notify = changes.pop("notifications", None)
    # Женский календарь живёт в самом профиле, а не в настройках
    # уведомлений: это не про сообщения, а про то, что видно на экране.
    show_cycle = changes.pop("cycle", None)

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        try:
            recalculated = await apply_profile(session, user, changes) if changes else False
        except ProfileError as error:
            return web.json_response({"error": str(error)}, status=400)
        if show_cycle is not None:
            user.cycle_enabled = bool(show_cycle)
            await session.commit()
        if isinstance(notify, dict):
            await notifications.save_prefs(session, request["user_id"], **notify)
        prefs = await notifications.prefs_for(session, request["user_id"])

    data = _profile_json(user, prefs)
    # Приложение показывает новую норму сразу: смена цели без видимой цифры
    # выглядит так, будто ничего не произошло.
    data["recalculated"] = recalculated
    return web.json_response(data)



async def send_to_chat(user_id: int, export) -> None:
    """Отдать файл ботом в переписку.

    Ссылкой на скачивание отдавать нельзя: внутри Telegram она открывается
    во встроенном браузере, где загрузка файла работает через раз, а сам
    адрес с личными данными жил бы в интернете. В чате файл остаётся
    навсегда и открывается с любого устройства.
    """
    from aiogram import Bot
    from aiogram.types import BufferedInputFile

    bot = Bot(token=config.BOT_TOKEN)
    try:
        await bot.send_document(
            user_id,
            BufferedInputFile(export.content, filename=export.filename),
            caption=export.caption(),
        )
    finally:
        await bot.session.close()


async def post_export(request: web.Request) -> web.Response:
    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        export = await build_export(session, user)

    await send_to_chat(user.id, export)
    return web.json_response({"filename": export.filename, "rows": export.rows,
                              "photos": export.photos_included})



async def get_menu(request: web.Request) -> web.Response:
    """Подбор блюда: что приготовить на этот приём пищи.

    Одна книга рецептов, три вопроса к ней. `mode=quick` — когда некогда,
    `mode=book` — вся книга, `mode=preps` — собрать из того, что заранее
    приготовлено. Сборка сверх справочника выключается параметром build=0.
    """
    from services import dish_picker

    meal = request.query.get("meal")
    allow_build = request.query.get("build", "1") != "0"
    mode = request.query.get("mode", dish_picker.MODE_BOOK)
    if mode not in dish_picker.MODES:
        mode = dish_picker.MODE_BOOK

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        result = await menu_board(session, user, meal_type=meal,
                                  allow_build=allow_build, mode=mode)

    return web.json_response(dict(result.to_dict(), mode=mode))


async def post_cube(request: web.Request) -> web.Response:
    """Кубик: что купить и съесть прямо сейчас.

    Диету и аллергии не спрашиваем — они уже есть в анкете. На экране
    остаётся только то, чего заранее знать нельзя: насколько человек голоден
    и чего ему хочется.
    """
    from services import catalogue, cube

    body = await request.json() if request.can_read_body else {}
    level = str(body.get("level") or "").strip()
    craving = str(body.get("craving") or "random").strip()
    no_spoon = bool(body.get("no_spoon"))
    # «Я уже в магазине»: один вопрос, сразу три ответа.
    in_store = bool(body.get("shop"))
    # Отмеченное в корзине: собираем только из того, что человек уже нашёл.
    basket = {str(code) for code in body.get("basket") or []} or None
    recent = [tuple(item) for item in body.get("recent") or []][: cube.REMEMBER]

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        products = await catalogue.products(session)


        # Чего не хватает сегодня — берём из дневника, а не спрашиваем.
        totals = await get_today_totals(session, user.id, timezone_name=request["timezone"])
        needs = set()
        if user.daily_protein_g and totals.protein_g < user.daily_protein_g * 0.75:
            needs.add(cube.NEED_PROTEIN)
        if user.daily_fiber_g and totals.fiber_g < user.daily_fiber_g * 0.75:
            needs.add(cube.NEED_FIBER)

        diet = user.diet_type.value if user.diet_type else "regular"
        allergies = {part.strip().lower() for part in (user.allergies or "").split(",")
                     if part.strip()}

        # Режим, который человек выбрал сам, менять нельзя. Тот, что мы
        # подставили за него, — можно: он был догадкой, а не просьбой.
        auto_level = not level
        if auto_level:
            # Человек в магазине не знает свой остаток — подставим сами.
            left = (user.daily_calories or 0) - totals.calories
            level = cube.level_for(left if left > 0 else None)

        limits = dict(
            no_spoon=no_spoon, exclude=allergies, basket=basket,
            needs=frozenset(needs),
            vegan=diet == "vegan", vegetarian=diet in {"vegan", "vegetarian"},
            gluten_free=diet == "gluten_free",
        )

        if in_store:
            offers = cube.shop_offers(products, craving=craving, **limits)
            cubes = [(label, item) for label, item in offers]
        else:
            found = cube.build(products, level=level, craving=craving,
                               recent=recent, limit=3, **limits)
            # Из отмеченного в корзине собираем что получится: человек уже
            # держит это в руках, отказывать ему из-за настроения глупо.
            if not found and basket:
                found = cube.build(products, level=level, craving="random",
                                   recent=recent, limit=3, **limits)
            # И тем более глупо отказывать из-за режима голода, который мы
            # выбрали за него сами: из четырёх продуктов с полки полноценный
            # приём не соберётся, а перекус соберётся.
            if not found and basket and auto_level:
                for lighter in cube.lighter_than(level):
                    found = cube.build(products, level=lighter, craving="random",
                                       recent=recent, limit=3, **limits)
                    if found:
                        level = lighter
                        break
            cubes = [("", item) for item in found]

    return web.json_response({
        "level": level,
        # Чтобы приложение могло объяснить, почему подобрало именно это.
        "needs": sorted(needs),
        "cubes": [dict(_cube_to_dict(item, products), label=label)
                  for label, item in cubes],
    })


async def get_friends(request: web.Request) -> web.Response:
    """Друзья: кто есть, чья неделя как идёт и общая цель.

    Наружу отдаётся только игровой слой. Вес, замеры, фотографии, калории и
    еда между людьми не передаются ни в каком виде.
    """
    from services import challenges, friends

    async with get_session() as session:
        user_id, tz = request["user_id"], request["timezone"]
        cards = await friends.board(session, user_id, timezone_name=tz)
        goal = await challenges.current(session, user_id, timezone_name=tz)
        code = await friends.invite_code(session, user_id)

    link = (f"https://t.me/{config.BOT_USERNAME}?start=friend_{code}"
            if config.BOT_USERNAME else "")
    return web.json_response({
        "friends": [card.to_dict() for card in cards],
        "count": len(cards) - 1,
        "limit": friends.MAX_FRIENDS,
        "invite": link,
        "challenge": goal.to_dict() if goal else None,
    })


async def post_friends(request: web.Request) -> web.Response:
    """Обновить ссылку-приглашение или убрать друга."""
    from services import friends

    body = await request.json() if request.can_read_body else {}
    async with get_session() as session:
        user_id = request["user_id"]

        if body.get("renew"):
            # Так отзывают ссылку, которую отправили не туда: старая
            # перестаёт работать сразу.
            await friends.invite_code(session, user_id, renew=True)
        elif body.get("remove"):
            try:
                other = int(body["remove"])
            except (TypeError, ValueError):
                return web.json_response({"error": "Непонятно, кого убрать"},
                                         status=400)
            await friends.disconnect(session, user_id, other)
        else:
            return web.json_response({"error": "Нечего делать"}, status=400)

    return await get_friends(request)


async def get_world(request: web.Request) -> web.Response:
    """Мой мир: какие места открыты, как они выросли и что дальше."""
    from services import world

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        tz = request["timezone"]
        payload = await world.state(session, user, timezone_name=tz)

        # Событие дня живёт здесь, а не на «Сегодня»: тот экран и так плотный.
        closed = await _quests_closed_today(session, user.id, timezone_name=tz)
        happening = await event_service.state(session, user.id, closed,
                                              timezone_name=tz)
        payload["event"] = happening.to_dict() if happening else None
        return web.json_response(payload)


async def _quests_closed_today(session, user_id: int, *, timezone_name: str) -> int:
    """Сколько заданий уже закрыто сегодня — по итогу дня, а не пересчётом."""
    from models import DayStat
    from sqlalchemy import select as sa_select
    from utils.timeframe import today_in

    row = (await session.execute(sa_select(DayStat).where(
        DayStat.user_id == user_id, DayStat.day == today_in(timezone_name)
    ))).scalar_one_or_none()
    if row is None or not row.quests_done:
        return 0
    return len([code for code in row.quests_done.split(",") if code])


async def post_my_prep(request: web.Request) -> web.Response:
    """Отметить заготовку приготовленной или убрать её из холодильника."""
    body = await request.json() if request.can_read_body else {}
    code = str(body.get("code", "")).strip()
    if not code:
        return web.json_response({"error": "Нужен код заготовки"}, status=400)

    async with get_session() as session:
        if body.get("done"):
            await prep_service.forget(session, request["user_id"], code)
        else:
            await prep_service.mark_made(session, request["user_id"], code,
                                         timezone_name=request["timezone"])
        fridge = await prep_service.mine(session, request["user_id"],
                                         timezone_name=request["timezone"])

    return web.json_response({"mine": [item.to_dict() for item in fridge]})


async def post_workout_pick(request: web.Request) -> web.Response:
    """Подобрать занятие под время, силы и место.

    Нового каталога нет: выбираем из тех же программ, что и всегда. Смысл в
    том, чтобы человек не выбирал сам, когда у него десять минут и мало сил.
    """
    from services import workout_picker

    body = await request.json() if request.can_read_body else {}
    quick = bool(body.get("quick"))

    try:
        minutes = max(int(body.get("minutes") or 30), 5)
    except (TypeError, ValueError):
        minutes = 30

    async with get_session() as session:
        state = await today_state(session, request["user_id"],
                                  timezone_name=request["timezone"])
        # Что делали в последние дни — чтобы не предлагать то же самое.
        recent = await recent_program_codes(session, request["user_id"],
                                            timezone_name=request["timezone"])

    energy = state.energy
    if quick:
        return web.json_response({
            "quick": True,
            "sets": [item.to_dict()
                     for item in workout_picker.quick_five(energy=energy, recent=recent)],
        })

    location = body.get("location") or None
    picks = workout_picker.pick(minutes_available=minutes, energy=energy,
                                location=location, recent=recent)
    return web.json_response({
        "quick": False,
        "energy": energy,
        "picks": [item.to_dict() for item in picks],
    })


async def post_shelf(request: web.Request) -> web.Response:
    """«Сфоткай полку»: что из этого мы умеем считать.

    Модель только называет продукты — калории, порции и сочетания считает
    Кубик. Наружу отдаём распознанное списком, чтобы человек подтвердил его
    до того, как увидит наборы: снять лишнее одним нажатием он может, а
    догадаться, почему бот предложил ерунду, — нет.
    """
    from services import catalogue, shelf_vision

    # Место на диске и деньги кончаются раньше всего именно на фотографиях.
    disk = disk_usage()
    if disk.full:
        logger.warning("Диск заполнен на %s%% — распознавание полки остановлено", disk.percent)
        return web.json_response(
            {"error": "На сервере кончается место — фото пока не принимаются"}, status=507)

    async with get_session() as session:
        if await usage.over_budget(session):
            return web.json_response(
                {"error": "Распознавание фото сегодня недоступно — исчерпан дневной "
                          "лимит. Отметь продукты в корзине руками, подбор работает."},
                status=429)
        if await usage.photo_limit_left(session, request["user_id"]) <= 0:
            return web.json_response(
                {"error": f"На сегодня распознавание фото исчерпано — это "
                          f"{config.PHOTO_LIMIT_PER_DAY} снимков в сутки. "
                          f"Отметь продукты в корзине руками."},
                status=429)

    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "photo":
        return web.json_response({"error": "Нет файла"}, status=400)

    content = bytearray()
    while chunk := await field.read_chunk():
        content.extend(chunk)
        if len(content) > MAX_PHOTO_BYTES:
            return web.json_response({"error": "Фото слишком большое (максимум 10 МБ)"},
                                     status=400)
    if not content:
        return web.json_response({"error": "Пустой файл"}, status=400)

    async with get_session() as session:
        products = await catalogue.products(session)

    spent: list = []
    try:
        shelf = await shelf_vision.recognize(
            bytes(content), {code: item.name for code, item in products.items()},
            on_usage=spent.append)
    except FoodRecognitionError as e:
        return web.json_response({"error": str(e)}, status=502)
    finally:
        # Запрос состоялся — значит, он уже стоил денег, даже если ответ
        # разобрать не удалось.
        await _record_usage(request["user_id"], "shelf", spent)

    return web.json_response({
        "codes": list(shelf.codes),
        "items": [{"code": code, "name": products[code].name}
                  for code in shelf.codes if code in products],
        # Еда, которую бот видит, но считать не умеет. Показываем честно:
        # иначе человек думает, что бот её проглядел.
        "other": list(shelf.other),
    })


async def _record_usage(user_id: int, kind: str, spent: list) -> None:
    """Записать расход на модель. Сбой учёта не должен ломать ответ человеку."""
    if not spent:
        return
    try:
        async with get_session() as session:
            for item in spent:
                await usage.record(session, user_id=user_id, kind=kind,
                                   model=config.VISION_MODEL, usage=item)
    except Exception:  # noqa: BLE001
        logger.exception("Не записался расход на распознавание полки")


async def get_basket(request: web.Request) -> web.Response:
    """Что можно отметить как «уже в корзине»."""
    from services import catalogue
    from seed.nutrition.cube_rules import BASKET

    async with get_session() as session:
        products = await catalogue.products(session)

    return web.json_response({"rows": [
        {"title": title,
         "items": [{"code": code, "name": products[code].name}
                   for code in codes if code in products]}
        for title, codes in BASKET
    ]})


def _cube_to_dict(item, products: dict) -> dict:
    low, high = item.kcal_range
    protein_low, protein_high = item.protein_range
    return {
        "title": item.title,
        "items": [{
            "code": part.code,
            "name": part.name,
            "measure": part.measure,
            "grams": part.grams,
            "swaps": [products[code].name for code in item.swaps.get(part.code, ())
                      if code in products],
        } for part in item.items],
        "kcal_low": low, "kcal_high": high,
        "protein_low": protein_low, "protein_high": protein_high,
        "kcal": round(item.kcal), "protein_g": round(item.protein_g, 1),
        "fat_g": round(item.fat_g, 1), "carbs_g": round(item.carbs_g, 1),
        "weight_g": round(sum(part.grams for part in item.items)),
        "signature": list(item.signature),
    }


async def get_preps(request: web.Request) -> web.Response:
    """Заготовки: что приготовить один раз и сколько это хранится.

    Сроки хранения — самая практичная часть её системы: без них заготовки
    превращаются в «наготовила и выбросила».
    """
    from sqlalchemy import select as sa_select

    async with get_session() as session:
        preps = (await session.execute(sa_select(Prep).order_by(Prep.name))).scalars().all()
        products = {p.code: p.name for p in
                    (await session.execute(sa_select(Product))).scalars()}
        components = (await session.execute(sa_select(PrepComponent))).scalars().all()
        # Что из этого уже стоит в холодильнике у конкретного человека.
        fridge = await prep_service.mine(session, request["user_id"],
                                         timezone_name=request["timezone"])

    by_prep: dict[int, list[dict]] = {}
    for item in components:
        by_prep.setdefault(item.prep_id, []).append({
            "name": products.get(item.product_code, item.product_code),
            "grams": round(item.grams),
            "raw": item.raw_amount,
        })

    return web.json_response({"preps": [
        {
            "code": prep.code,
            "name": prep.name,
            "portions": prep.portions,
            "minutes": prep.minutes,
            "fridge": prep.fridge_days,
            "freezer": prep.freezer_days,
            "ideas": prep.ideas,
            "instructions": prep.instructions,
            "source": prep.source,
            "batch_g": round(prep.batch_g),
            "per100": {
                "calories": round(prep.kcal),
                "protein_g": round(prep.protein_g, 1),
                "fat_g": round(prep.fat_g, 1),
                "carbs_g": round(prep.carbs_g, 1),
                "fiber_g": round(prep.fiber_g, 1),
            },
            "components": by_prep.get(prep.id, []),
        }
        for prep in preps
    ], "mine": [item.to_dict() for item in fridge]})


async def post_crash(request: web.Request) -> web.Response:
    """Приложение сообщает о своей поломке на телефоне человека.

    Серверная ошибка видна в логах, ошибка в браузере — нигде. Человек в
    этот момент смотрит на пустой экран и решает, что бот сломался совсем.
    """
    from services import crashes

    body = await request.json() if request.can_read_body else {}
    await crashes.report_client(
        request.app.get(BOT_KEY),
        body.get("message") or "",
        where=str(body.get("screen") or "приложение")[:60],
        place=body.get("place") or "",
        user_id=request.get("user_id"),
    )
    # Ответ всегда успешный: приложению незачем разбираться, как прошло
    # сообщение о поломке — у него и так уже что-то сломалось.
    return web.json_response({"ok": True})


async def post_feedback(request: web.Request) -> web.Response:
    """«Что-то не так» из приложения.

    Человек пишет прямо там, где споткнулся: выгонять его в чат ради жалобы
    значит не получить жалобу вовсе.
    """
    from services import feedback

    body = await request.json() if request.can_read_body else {}
    text = feedback.clean(body.get("text") or "")
    if not text:
        return web.json_response({"error": "Напиши, что случилось"}, status=400)

    bot = request.app.get(BOT_KEY)
    if bot is None or not config.ADMIN_IDS:
        return web.json_response(
            {"error": "Сейчас передать некому — бот ещё настраивается."}, status=503)

    user_id = request["user_id"]
    if not feedback.allowed(user_id):
        return web.json_response(
            {"error": "Я уже передала твои сообщения — давай подождём ответа."},
            status=429)

    async with get_session() as session:
        user = await session.get(User, user_id)
        name = (user.full_name or "").strip() if user else ""

    from handlers.feedback import answer_button

    screen = str(body.get("screen") or "").strip()[:40]
    delivered = await feedback.deliver(
        bot,
        feedback.Report(user_id=user_id, name=name,
                        where=f"приложение, экран «{screen}»" if screen else "приложение",
                        text=text),
        keyboard=answer_button(user_id),
    )
    if not delivered:
        return web.json_response(
            {"error": "Не получилось передать. Попробуй ещё раз позже."}, status=502)
    return web.json_response({"ok": True})


async def post_steps(request: web.Request) -> web.Response:
    """Внести шаги за сегодня.

    Число заменяет прежнее, а не прибавляется к нему: телефон показывает
    итог с начала суток, и человек, заглянувший трижды, иначе получил бы
    тройной день.
    """
    from services import steps as step_service

    body = await request.json() if request.can_read_body else {}
    value = step_service.clean_steps(body.get("steps"))
    if value is None:
        return web.json_response({"error": "Это не похоже на число шагов"}, status=400)

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        await step_service.record(session, user.id, value,
                                  timezone_name=request["timezone"])
        state = await step_service.state(session, user,
                                         timezone_name=request["timezone"])
    return web.json_response(state.to_dict())


async def get_steps_board(request: web.Request) -> web.Response:
    """Кто сколько прошёл за неделю: своя команда и всё приложение.

    Наружу отдаётся только имя и шаги. Ни веса, ни калорий, ни еды: шагами
    соревноваться безвредно, остальным — нет.
    """
    from services import steps as step_service
    from services import teams

    async with get_session() as session:
        user_id, tz = request["user_id"], request["timezone"]
        team = await teams.board(session, user_id, timezone_name=tz)
        top = await step_service.global_top(session, me=user_id, timezone_name=tz)

        # Прошлая неделя: без неё понедельник обнуляет всё, чего человек
        # добился, и возвращаться в таблицу становится незачем.
        last_period = step_service.last_week_bounds(today_in(tz))
        last_rows = await step_service.global_top(session, me=user_id, limit=10 ** 6,
                                                  timezone_name=tz, period=last_period)
        mine = next((row for row in last_rows if row.user_id == user_id), None)

    invite = ""
    if team is not None and config.BOT_USERNAME:
        invite = f"https://t.me/{config.BOT_USERNAME}?start=team_{team.code}"

    return web.json_response({
        "team": dict(team.to_dict(), invite=invite) if team else None,
        "top": [row.to_dict() for row in top],
        "place": step_service.place_of(top, user_id),
        "last": {
            "steps": mine.steps if mine else 0,
            "days": mine.days if mine else 0,
            "place": step_service.place_of(last_rows, user_id),
        },
        "cap": step_service.RANKED_CAP,
        "max_members": teams.MAX_MEMBERS,
    })


async def post_team(request: web.Request) -> web.Response:
    """Создать команду, вступить в чужую, переименовать свою или выйти."""
    from services import teams

    body = await request.json() if request.can_read_body else {}
    action = str(body.get("action") or "").strip()
    user_id = request["user_id"]

    async with get_session() as session:
        if action == "create":
            status, _ = await teams.create(session, user_id, body.get("name") or "")
        elif action == "join":
            status, _ = await teams.join(session, user_id, body.get("code") or "")
        elif action == "rename":
            status = "ok" if await teams.rename(session, user_id, body.get("name") or "") \
                else "no_team"
        elif action == "leave":
            status = "ok" if await teams.leave(session, user_id) else "no_team"
        else:
            return web.json_response({"error": "Непонятное действие"}, status=400)

    problems = {
        "no_name": "Придумай название команды",
        "already": "Ты уже в команде. Сначала выйди из неё.",
        "same": "Ты уже в этой команде",
        "no_team": "Такой команды нет — проверь код",
        "full": "В команде уже нет свободных мест",
    }
    if status != "ok":
        return web.json_response({"error": problems.get(status, "Не получилось")},
                                 status=400)
    return web.json_response({"ok": True})


async def get_steps_sync(request: web.Request) -> web.Response:
    """Личная ссылка присылки и инструкция к ней."""
    from services import step_sync
    from services import steps as step_service

    async with get_session() as session:
        user = await session.get(User, request["user_id"])
        renew = bool((await request.json()).get("renew")) \
            if request.method == "POST" and request.can_read_body else False
        token = await step_service.sync_token(session, user, renew=renew)
        synced = await step_service.last_sync(session, user.id)

    return web.json_response({
        "link": step_sync.link_for(token),
        "why": step_sync.WHY,
        "iphone": step_sync.IPHONE,
        "android": step_sync.ANDROID,
        "safety": step_sync.SAFETY,
        "no_site": step_sync.NO_SITE,
        "last": to_local(synced, request["timezone"]).strftime("%d.%m в %H:%M")
                if synced else "",
    })


async def push_steps(request: web.Request) -> web.Response:
    """Телефон присылает шаги сам, по личной ссылке.

    Живёт вне /api/ нарочно: подписи Telegram здесь нет и быть не может —
    стучится не приложение, а «Команды» на айфоне или автоматизация на
    Android, по расписанию и без участия человека. Вместо подписи — ключ в
    самой ссылке.

    Принимаем и число в адресе (`?steps=8432`), и JSON в теле. Первое проще
    собрать в «Командах» одной строкой, второе — то, что шлют привычные
    автоматизации; отказывать ни тем, ни другим незачем.
    """
    from services import steps as step_service

    token = request.match_info.get("token", "")
    async with get_session() as session:
        user = await step_service.by_token(session, token)
        if user is None:
            # Про чужой ключ не рассказываем ничего сверх того, что он не наш.
            return web.json_response({"error": "Ссылка не подходит"}, status=404)

        if not step_service.push_allowed(token):
            return web.json_response(
                {"error": "Слишком часто. Достаточно нескольких раз в день."},
                status=429)

        raw = request.query.get("steps")
        if raw is None and request.can_read_body:
            body = await request.json()
            raw = body.get("steps") if isinstance(body, dict) else None

        value = step_service.clean_steps(raw)
        if value is None:
            return web.json_response(
                {"error": "Не вижу числа шагов. Ожидаю ?steps=8432 или "
                          "{\"steps\": 8432}"}, status=400)

        tz = user.timezone or DEFAULT_TIMEZONE
        await step_service.record(session, user.id, value, timezone_name=tz,
                                  source=step_service.SOURCE_PHONE)
        state = await step_service.state(session, user, timezone_name=tz)

    # Ответ человеческий: его видно, если открыть ссылку в браузере — так
    # проверяют, что настройка получилась.
    return web.json_response({
        "ok": True,
        "steps": state.today,
        "goal": state.goal,
        "done": state.done,
        "text": f"Записано {state.today} шагов из {state.goal}",
    })


async def get_cycle(request: web.Request) -> web.Response:
    """Состояние цикла на сегодня. Только для тех, кому он нужен."""
    user_id, tz = request["user_id"], request["timezone"]
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not _cycle_shown(user):
            return web.json_response({"available": False})
        state = await cycle.state(session, user_id, today_in(tz))
    return web.json_response({"available": True, **state.to_dict()})


async def post_cycle(request: web.Request) -> web.Response:
    """Отметить или снять начало месячных. Повторное нажатие снимает."""
    user_id, tz = request["user_id"], request["timezone"]
    body = await request.json()
    raw = (body or {}).get("day")

    try:
        day = date.fromisoformat(raw) if raw else today_in(tz)
    except ValueError:
        return web.json_response({"error": "Не разобрал дату"}, status=400)

    if day > today_in(tz):
        return web.json_response({"error": "Будущее отметить нельзя"}, status=400)

    async with get_session() as session:
        user = await session.get(User, user_id)
        if not _cycle_shown(user):
            return web.json_response({"error": "Календарь выключен"}, status=400)
        marked = await cycle.mark(session, user_id, day)
        state = await cycle.state(session, user_id, today_in(tz))
    return web.json_response({"available": True, "marked": marked,
                             **state.to_dict()})


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
    app.router.add_get("/api/cycle", get_cycle)
    app.router.add_post("/api/cycle", post_cycle)
    app.router.add_post("/api/measurements", post_measurement)
    app.router.add_post("/api/photos", post_photo)
    app.router.add_get("/api/photos/{photo_id}", get_photo)
    app.router.add_delete("/api/photos/{photo_id}", delete_photo)
    app.router.add_get("/api/workouts", get_workouts)
    app.router.add_post("/api/workouts/log", post_workout_log)
    app.router.add_post("/api/meals", post_meal)
    app.router.add_post("/api/moment", post_moment)
    app.router.add_post("/api/moment/confirm", confirm_moment)
    app.router.add_post("/api/moment/facts", recount_moment)
    app.router.add_post("/api/checkin", post_checkin)
    app.router.add_get("/api/profile", get_profile)
    app.router.add_patch("/api/profile", patch_profile)
    app.router.add_post("/api/export", post_export)
    app.router.add_get("/api/menu", get_menu)
    app.router.add_post("/api/cube", post_cube)
    app.router.add_get("/api/cube/basket", get_basket)
    app.router.add_post("/api/cube/shelf", post_shelf)
    app.router.add_post("/api/crash", post_crash)
    app.router.add_post("/api/feedback", post_feedback)
    app.router.add_post("/api/steps", post_steps)
    # Присылка с телефона: вне /api/, потому что подписи Telegram там нет.
    app.router.add_route("*", "/hook/steps/{token}", push_steps)
    app.router.add_get("/api/steps/board", get_steps_board)
    app.router.add_get("/api/steps/sync", get_steps_sync)
    app.router.add_post("/api/steps/sync", get_steps_sync)
    app.router.add_post("/api/team", post_team)
    app.router.add_post("/api/workouts/pick", post_workout_pick)
    app.router.add_get("/api/preps", get_preps)
    app.router.add_post("/api/preps/mine", post_my_prep)
    app.router.add_get("/api/world", get_world)
    app.router.add_get("/api/friends", get_friends)
    app.router.add_post("/api/friends", post_friends)
