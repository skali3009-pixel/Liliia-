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

import anthropic

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
    "- Указывай реалистичный вес порции, её КБЖУ и клетчатку. В carbs_g — усвояемые "
    "углеводы без клетчатки, в fiber_g — пищевые волокна.\n"
    "- Если не хватает клетчатки, добавляй в варианты овощи, зелень, бобовые, ягоды "
    "или цельнозерновые — но не в ущерб остальным условиям.\n"
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
                        "carbs_g": {"type": "number",
                                    "description": "Углеводы без клетчатки, г"},
                        "fiber_g": {"type": "number",
                                    "description": "Клетчатка, г; 0, если её нет"},
                        "why": {"type": "string", "description": "Одна фраза: чем хорош сейчас"},
                    },
                    "required": ["name", "weight_g", "calories", "protein_g", "fat_g",
                                 "carbs_g", "fiber_g", "why"],
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
    fiber_g: float = 0.0

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
        f"Клетчатки до дневной цели осталось {left.fiber_g} г.\n"
        f"{gap_line}\n"
        f"Ограничения: {'; '.join(limits) if limits else 'нет'}.\n"
        f"Цель: {user.goal.value if user.goal else 'поддержание'}."
    )


async def suggest_meals(user: User, left: Remaining, norms: dict[str, float]) -> list[Suggestion]:
    """Три варианта под остаток нормы."""
    # Та же обработка ошибок Claude, что и в распознавании еды по фото
    # (services/food_vision.py::_analyze) — раньше её тут не было, и любой
    # сбой API (перегрузка, лимит запросов) улетал необработанным до общего
    # 500-обработчика: пользователь видел голое «Что-то сломалось на сервере»
    # вместо человеческого объяснения.
    try:
        response = await get_client().messages.create(
            model=config.VISION_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[SUGGEST_TOOL],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": build_request(user, left, norms)}],
        )
    except anthropic.AuthenticationError:
        raise VisionNotConfigured(
            "Ключ Anthropic не принят — он неверный, отозван или скопирован не полностью.\n\n"
            "Создай новый на console.anthropic.com/settings/keys и пропиши его заново."
        ) from None
    except anthropic.PermissionDeniedError:
        raise VisionNotConfigured(
            "У ключа нет доступа к модели. Проверь настройки ключа в кабинете Anthropic."
        ) from None
    except anthropic.RateLimitError:
        raise FoodRecognitionError(
            "Слишком много запросов подряд. Подожди минуту и попробуй ещё раз."
        ) from None
    except anthropic.APIStatusError as e:
        details = str(getattr(e, "message", "") or e).lower()
        if "credit" in details or "billing" in details or "quota" in details:
            raise FoodRecognitionError(
                "На счёте Anthropic закончились деньги — пополни баланс "
                "на console.anthropic.com/settings/billing."
            ) from None
        logger.warning("Claude ответил %s: %s", e.status_code, details[:300])
        raise FoodRecognitionError(
            f"Claude ответил ошибкой ({e.status_code}). Попробуй ещё раз чуть позже."
        ) from None
    except anthropic.APIConnectionError:
        raise FoodRecognitionError(
            "Не получилось связаться с Claude — похоже, у сервера проблемы с сетью."
        ) from None

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
            fiber_g=max(float(meal.get("fiber_g", 0)), 0),
            why=str(meal.get("why", "")).strip()[:160],
        )
        for meal in meals
        if meal.get("name")
    ]


__all__ = ["Suggestion", "VisionNotConfigured", "build_request", "suggest_meals"]
