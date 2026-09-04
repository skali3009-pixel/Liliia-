"""Подбор блюд под остаток нормы на сегодня.

Остаток и правило тарелки считаются на месте, а конкретные варианты
подбирает Claude: он учитывает аллергии, тип питания, время суток и то,
что уже съедено. Ответ приходит вызовом инструмента со строгой схемой —
как и при распознавании еды.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import config
from models import User
from services.food_vision import FoodRecognitionError, VisionNotConfigured, get_client
from utils.macros import GAP_LABELS, Remaining, dominant_gap
from utils.meal_time import MEAL_TYPE_RU, guess_meal_type
from utils.timeframe import get_zone

logger = logging.getLogger(__name__)

MAX_TOKENS = 1500

DIET_RU = {
    "regular": "обычное питание",
    "vegan": "веганское питание (без продуктов животного происхождения)",
    "vegetarian": "вегетарианское питание (без мяса и рыбы)",
    "gluten_free": "питание без глютена",
}

SYSTEM_PROMPT = (
    "Ты — нутрициолог, который подсказывает, что съесть прямо сейчас, чтобы уложиться "
    "в дневную норму.\n"
    "\n"
    "Правила:\n"
    "- Предлагай три варианта: простые блюда из обычных продуктов, которые можно "
    "приготовить за 15-20 минут или купить готовыми.\n"
    "- Каждый вариант должен помещаться в оставшиеся калории и по возможности "
    "закрывать недобор нужного макронутриента.\n"
    "- Обязательно соблюдай ограничения по питанию и аллергии — это жёсткое условие, "
    "а не пожелание.\n"
    "- Учитывай время суток: утром не предлагай тяжёлый ужин, вечером — сладкие каши.\n"
    "- Указывай реалистичный вес порции и её КБЖУ.\n"
    "- В поле why — одна короткая фраза, чем этот вариант хорош именно сейчас "
    "(например, «закроет недобор белка, всего 320 ккал»).\n"
    "- Названия и объяснения — на русском языке.\n"
    "\n"
    "Всегда вызывай инструмент suggest_meals. Не отвечай обычным текстом."
)

SUGGEST_TOOL: dict[str, Any] = {
    "name": "suggest_meals",
    "description": "Предложить блюда под остаток дневной нормы.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "meals": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Название блюда по-русски"},
                        "weight_g": {"type": "number", "description": "Вес порции, г"},
                        "calories": {"type": "number"},
                        "protein_g": {"type": "number"},
                        "fat_g": {"type": "number"},
                        "carbs_g": {"type": "number"},
                        "why": {"type": "string", "description": "Одна фраза: чем хорош сейчас"},
                    },
                    "required": ["name", "weight_g", "calories", "protein_g", "fat_g",
                                 "carbs_g", "why"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["meals"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class Suggestion:
    name: str
    weight_g: float
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float
    why: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_request(user: User, left: Remaining, norms: dict[str, float]) -> str:
    """Собрать описание ситуации для модели."""
    now = datetime.now(get_zone(user.timezone))
    meal_type = MEAL_TYPE_RU[guess_meal_type(now)]

    gap = dominant_gap(left, norms)
    gap_line = (
        f"Сильнее всего не хватает {GAP_LABELS[gap]}."
        if gap
        else "Норма почти выбрана — предложи что-то лёгкое."
    )

    limits = []
    if user.diet_type:
        limits.append(DIET_RU.get(user.diet_type.value, "обычное питание"))
    if user.allergies:
        limits.append(f"аллергии и непереносимости: {user.allergies}")

    return (
        f"Сейчас {now.strftime('%H:%M')}, ближайший приём пищи — {meal_type}.\n"
        f"Осталось на сегодня: {left.calories} ккал, "
        f"белки {left.protein_g} г, жиры {left.fat_g} г, углеводы {left.carbs_g} г.\n"
        f"{gap_line}\n"
        f"Ограничения: {'; '.join(limits) if limits else 'нет'}.\n"
        f"Цель: {user.goal.value if user.goal else 'поддержание'}."
    )


async def suggest_meals(user: User, left: Remaining, norms: dict[str, float]) -> list[Suggestion]:
    """Три варианта под остаток нормы."""
    response = await get_client().messages.create(
        model=config.VISION_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[SUGGEST_TOOL],
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": build_request(user, left, norms)}],
    )

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        logger.warning("Модель не вызвала инструмент, stop_reason=%s", response.stop_reason)
        raise FoodRecognitionError("Не получилось подобрать блюда. Попробуй ещё раз.")

    meals = dict(tool_use.input).get("meals") or []
    return [
        Suggestion(
            name=str(meal.get("name", "")).strip()[:80],
            weight_g=max(float(meal.get("weight_g", 0)), 0),
            calories=max(float(meal.get("calories", 0)), 0),
            protein_g=max(float(meal.get("protein_g", 0)), 0),
            fat_g=max(float(meal.get("fat_g", 0)), 0),
            carbs_g=max(float(meal.get("carbs_g", 0)), 0),
            why=str(meal.get("why", "")).strip()[:160],
        )
        for meal in meals
        if meal.get("name")
    ]


__all__ = ["Suggestion", "VisionNotConfigured", "build_request", "suggest_meals"]
