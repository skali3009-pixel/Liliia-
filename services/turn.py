"""«Твой ход» и гепард — одним ответом, для приложения и для чата.

Весь ум приложения жил только в мини-приложении: подсказка «что сделать
сейчас» и реакция гепарда собирались прямо в обработчике экрана «Сегодня».
Человеку, который ведёт дневник перепиской в чате, не доставалось ничего.

Поэтому сборка переехала сюда целиком. Приложение и бот берут одно и то же
из одного места: если правило подсказки изменится, оно изменится сразу в
обоих, а не в одном из двух — что и есть самый частый способ развести их
поведение и потом полдня искать, почему.

Здесь только сборка. Правила подсказки — в services/context.py, настроения
гепарда — в utils/cheetah.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from services import context
from services.checkins import today_state
from services.gamification import (days_away, remember_suggestion, suggestions_today,
                                   sync_today)
from services.meals import get_today_totals, list_today_meals
from services.preps import expiring_names
from services.water import today_total_ml
from utils.cheetah import Mood
from utils.cheetah import mood as cheetah_mood
from utils.timeframe import DEFAULT_TIMEZONE
from utils.plural import plural


def day_context(user: User, tz: str, *, totals, water, meals, state, game,
                suggested, days_since_measure=None, preps=()):  # noqa: PLR0913
    """Собрать срез дня. Ничего не требует: чего нет, того нет."""
    return context.DayContext(
        hour=context.hour_in(tz),
        calories=totals.calories, calories_target=user.daily_calories or None,
        protein_g=totals.protein_g, protein_target=user.daily_protein_g or None,
        fiber_g=totals.fiber_g, fiber_target=user.daily_fiber_g or None,
        water_ml=water, water_target=user.daily_water_ml or None,
        meals_logged=meals,
        steps=(game.get("steps") or {}).get("today", 0),
        steps_goal=(game.get("steps") or {}).get("goal") or None,
        steps_logged=bool((game.get("steps") or {}).get("today")),
        workouts_today=game.get("workouts_today", 0),
        days_since_measure=days_since_measure,
        energy=state.energy, stress=state.stress,
        checkin_done=not state.is_empty,
        streak=game.get("streak", 0),
        quests_left=game.get("quests_total", 0) - game.get("quests_done", 0),
        preps_expiring=tuple(preps),
        already_suggested=tuple(suggested),
    )


async def next_action(session: AsyncSession, user: User, tz: str, **parts):
    """Одно действие для «Твоего хода» — и отметка, что его показали."""
    shown = await suggestions_today(session, user.id, timezone_name=tz)
    action = context.next_action(day_context(user, tz, suggested=shown, **parts))
    if action is not None:
        await remember_suggestion(session, user.id, action.code, timezone_name=tz)
    return action


async def cheetah_for(session: AsyncSession, user: User, tz: str, *,
                      game: dict, state, water: float,
                      world_unlock: bool = False) -> Mood:
    """Реакция гепарда. Он ничего не советует — он отзывается на день."""
    return cheetah_mood(
        hour=context.hour_in(tz),
        energy=state.energy, stress=state.stress,
        water_share=(water / user.daily_water_ml) if user.daily_water_ml else 1.0,
        workouts_today=game.get("workouts_today", 0),
        streak=game.get("streak", 0),
        days_away=await days_away(session, user.id, timezone_name=tz),
        new_awards=len(game.get("new_awards") or []),
        world_unlock=world_unlock,
        quests_done=game.get("quests_done", 0),
        quests_total=game.get("quests_total", 0),
    )


@dataclass(frozen=True)
class Turn:
    """Что сказать человеку прямо сейчас: реакция, ход и цифры дня."""

    cheetah: Mood
    action: context.Action | None
    calories: float
    calories_target: int | None
    water_ml: int
    water_target: int | None
    quests_done: int
    quests_total: int
    level: int
    streak: int
    steps: int = 0
    steps_goal: int = 0
    hour: int = 12


async def build(session: AsyncSession, user: User, *,
                timezone_name: str | None = None) -> Turn:
    """Собрать «твой ход» для чата: те же данные, что видит приложение."""
    tz = timezone_name or user.timezone or DEFAULT_TIMEZONE

    totals = await get_today_totals(session, user.id, timezone_name=tz)
    meals = await list_today_meals(session, user.id, timezone_name=tz)
    water = await today_total_ml(session, user.id, timezone_name=tz)
    state = await today_state(session, user.id, timezone_name=tz)
    game = await sync_today(
        session, user, meals_count=len(meals), calories=totals.calories,
        fiber_g=totals.fiber_g, water_ml=water, timezone_name=tz,
        stress_marked=state.stress is not None,
    )

    parts = dict(totals=totals, water=water, meals=len(meals), state=state, game=game,
                 days_since_measure=game.get("days_since_measure"),
                 preps=await expiring_names(session, user.id, timezone_name=tz))
    action = await next_action(session, user, tz, **parts)

    return Turn(
        cheetah=await cheetah_for(session, user, tz, game=game, state=state, water=water),
        action=action,
        calories=totals.calories, calories_target=user.daily_calories or None,
        water_ml=round(water), water_target=user.daily_water_ml or None,
        quests_done=game.get("quests_done", 0),
        quests_total=game.get("quests_total", 0),
        level=game.get("level", 1), streak=game.get("streak", 0),
        steps=(game.get("steps") or {}).get("today", 0),
        steps_goal=(game.get("steps") or {}).get("goal", 0),
        hour=context.hour_in(tz),
    )


def game_lines(game: dict) -> list[str]:
    """Уровень, стрик и только что закрытые задания — короткой припиской."""
    if not game:
        return []

    lines = [""]
    for code in game.get("just_completed", []):
        quest = next((q for q in game["quests"] if q["code"] == code), None)
        if quest:
            lines.append(f"✅ Задание закрыто: {quest['title']} +{quest['xp']} 💎")

    for award in game.get("new_awards", []):
        lines.append(f"{award['icon']} Новая награда: {award['title']}")

    progress = f"💎 Уровень {game['level']} · {game['xp_in_level']}/{game['xp_to_next']}"
    if game.get("streak"):
        days = plural(game["streak"], "день", "дня", "дней")
        progress += f" · 🔥 {game['streak']} {days} подряд"
    lines.append(progress)
    return lines



# Куда ведёт подсказка в чате. В приложении кнопка открывает экран, в чате
# экранов нет — зато есть кнопки нижнего меню, и человеку понятнее, когда
# ему называют ту самую кнопку, которую он видит.
CHAT_BUTTON = {
    "water": "💧 Вода",
    "steps": "👟 Шаги",
    "meal": "📷 Добавить еду",
    "cube": "🍽️ Что съесть",
    "workout": "🏋️ Тренировка",
    "progress": "📊 Прогресс",
}


def chat_hint(action: context.Action | None) -> str | None:
    """Какую кнопку нажать. None — значит, это делается только в приложении."""
    if action is None:
        return None
    button = CHAT_BUTTON.get(action.target)
    return f"→ нажми «{button}»" if button else None


def render(turn: Turn) -> str:
    """Сообщение для чата: реакция гепарда, цифры дня и один ход."""
    lines = [f"{turn.cheetah.emoji} {turn.cheetah.line}", ""]

    if turn.calories_target:
        left = round(turn.calories_target - turn.calories)
        lines.append(f"🔥 {round(turn.calories)} из {turn.calories_target} ккал"
                     + (f" · осталось {left}" if left > 0 else " · норма набрана"))
    if turn.water_target:
        lines.append(f"💧 Вода {turn.water_ml} из {turn.water_target} мл")
    if turn.steps_goal:
        lines.append(f"👟 Шаги {turn.steps} из {turn.steps_goal}")
    if turn.quests_total:
        lines.append(f"🎯 Задания дня: {turn.quests_done} из {turn.quests_total}")
    progress = f"💎 Уровень {turn.level}"
    if turn.streak:
        days = plural(turn.streak, "день", "дня", "дней")
        progress += f" · 🔥 {turn.streak} {days} подряд"
    lines.append(progress)

    if turn.action is None:
        # Предлагать нечего по трём разным причинам, и говорить о них одной
        # фразой нельзя. «Всё идёт как надо» в одиннадцать вечера человеку с
        # шестью незакрытыми заданиями — неправда, а неправда в мелочи бьёт
        # по доверию ко всему остальному, что говорит бот.
        if turn.hour >= context.QUIET_FROM or turn.hour < context.QUIET_TO:
            lines += ["", "Уже ночь — на сегодня всё. Отдыхай."]
        elif turn.quests_total and turn.quests_done >= turn.quests_total:
            lines += ["", "Всё на сегодня закрыто. Можно выдохнуть."]
        else:
            lines += ["", "Ничего срочного прямо сейчас."]
        return "\n".join(lines)

    # Бот отвечает обычным текстом, без разметки: жирного тут не будет.
    lines += ["", "🐆 Твой ход", turn.action.text]
    hint = chat_hint(turn.action)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


__all__ = ["CHAT_BUTTON", "Turn", "build", "chat_hint", "cheetah_for",
           "day_context", "game_lines", "next_action", "render"]
