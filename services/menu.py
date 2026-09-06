"""«Подобрать блюдо»: что показать человеку прямо сейчас.

Собирает вместе всё остальное: считает бюджет приёма, берёт подходящее из
меню Анастасии, при нехватке добирает блюдами, собранными по её принципам,
и никогда не выдумывает цифры — КБЖУ везде считает арифметика.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import MealTypeEnum, Product, User
from services import dish_picker, method
from services.dish_builder import build_dish
from services.food_vision import FoodRecognitionError
from services.meals import get_today_totals
from utils.macros import dominant_gap, remaining
from utils.meal_budget import meal_budget
from utils.meal_time import guess_meal_type
from utils.timeframe import get_zone

logger = logging.getLogger(__name__)

WANTED = 3
MEAL_CODES = {"breakfast": MealTypeEnum.BREAKFAST, "lunch": MealTypeEnum.LUNCH,
              "dinner": MealTypeEnum.DINNER, "snack": MealTypeEnum.SNACK}
MEAL_RU = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин", "snack": "перекус"}


@dataclass
class Offer:
    """Один вариант для показа. Отличается только пометкой автора."""

    name: str
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float
    weight_g: float
    minutes: int
    reason: str
    author: bool = False
    source: str = ""
    code: str = ""
    scale: float = 1.0
    instructions: str = ""
    components: list[dict] | None = None
    preps: list[str] = field(default_factory=list)
    notes: str = ""
    approximate: bool = False

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "calories": round(self.calories),
            "protein_g": round(self.protein_g, 1),
            "fat_g": round(self.fat_g, 1),
            "carbs_g": round(self.carbs_g, 1),
            "fiber_g": round(self.fiber_g, 1),
            "weight_g": round(self.weight_g),
            "minutes": self.minutes,
            "reason": self.reason,
            "author": self.author,
            "source": self.source,
            "scale": round(self.scale, 2),
            "instructions": self.instructions,
            "components": self.components or [],
            "preps": self.preps,
            "notes": self.notes,
            "approximate": self.approximate,
        }


@dataclass
class Board:
    """Всё, что нужно экрану подбора."""

    meal_type: str
    meal_name: str
    budget: int
    left_calories: int
    gap: str | None
    hint: str
    offers: list[Offer]
    approximate: bool = False

    def to_dict(self) -> dict:
        return {
            "meal_type": self.meal_type,
            "meal_name": self.meal_name,
            "budget": self.budget,
            "left_calories": self.left_calories,
            "gap": self.gap,
            "hint": self.hint,
            "approximate": self.approximate,
            "offers": [offer.to_dict() for offer in self.offers],
        }


def default_meal(timezone_name: str | None) -> str:
    """Какой приём предложить по умолчанию — по часам человека."""
    guessed = guess_meal_type(datetime.now(get_zone(timezone_name)))
    for code, enum_value in MEAL_CODES.items():
        if enum_value is guessed:
            return code
    return "lunch"


async def _budget_and_gap(session: AsyncSession, user: User, meal_type: str
                          ) -> tuple[int, int, str | None]:
    totals = await get_today_totals(session, user.id, timezone_name=user.timezone)
    norms = {
        "calories": user.daily_calories or 0,
        "protein_g": user.daily_protein_g or 0,
        "fat_g": user.daily_fat_g or 0,
        "carbs_g": user.daily_carbs_g or 0,
        "fiber_g": user.daily_fiber_g or 0,
    }
    left = remaining(
        {"calories": totals.calories, "protein_g": totals.protein_g, "fat_g": totals.fat_g,
         "carbs_g": totals.carbs_g, "fiber_g": totals.fiber_g},
        norms,
    )
    gap = dominant_gap(left, norms)
    # Клетчатка живёт отдельно от БЖУ: если её сильно не хватает, она важнее.
    if norms["fiber_g"] and left.fiber_g / norms["fiber_g"] > 0.6:
        gap = "fiber_g"

    budget = meal_budget(
        now=datetime.now(get_zone(user.timezone)),
        daily_calories=norms["calories"],
        remaining_calories=left.calories,
    )
    # Человек мог выбрать приём вручную — тогда считаем долю для него.
    if MEAL_CODES.get(meal_type) is not budget.meal_type:
        from utils.meal_budget import MEAL_SHARES

        share = MEAL_SHARES.get(MEAL_CODES.get(meal_type, MealTypeEnum.LUNCH), 0.3)
        target = min(norms["calories"] * share, max(left.calories, 0)) or norms["calories"] * share
        return int(round(target)), left.calories, gap

    return budget.target_kcal, left.calories, gap


def _from_pick(pick: dish_picker.Pick) -> Offer:
    return Offer(
        code=pick.dish.code, name=pick.dish.name, calories=pick.kcal,
        protein_g=pick.protein_g, fat_g=pick.fat_g, carbs_g=pick.carbs_g,
        fiber_g=pick.fiber_g, weight_g=pick.weight_g, minutes=pick.dish.minutes,
        reason=pick.reason, author=pick.dish.author, source=pick.dish.source,
        scale=pick.scale, instructions=pick.dish.instructions,
        preps=pick.preps, notes=pick.dish.notes,
    )


async def _built_offers(session: AsyncSession, user: User, *, meal_type: str,
                        budget: float, gap: str | None, avoid: list[str],
                        count: int) -> list[Offer]:
    """Добрать вариантов сборкой по методу. Молча пропускаем неудачи."""
    if count <= 0:
        return []
    products = list((await session.execute(select(Product))).scalars())
    offers: list[Offer] = []
    seen = list(avoid)

    for _ in range(count):
        try:
            built = await build_dish(user, meal_type=meal_type, budget=budget,
                                     products=products, gap=gap, avoid=seen)
        except FoodRecognitionError as error:
            logger.info("Сборка блюда не удалась: %s", error)
            break
        except Exception:
            logger.exception("Сборка блюда сломалась")
            break

        offers.append(Offer(
            name=built["name"], calories=built["kcal"], protein_g=built["protein_g"],
            fat_g=built["fat_g"], carbs_g=built["carbs_g"], fiber_g=built["fiber_g"],
            weight_g=built["weight_g"], minutes=built["minutes"],
            reason=f"{built['kcal']:.0f} ккал на порцию",
            instructions=built["instructions"],
            components=[{"name": c["product_code"], "grams": round(c["grams"]),
                         "raw": c["raw_amount"], "seasoning": False, "role": c["role"]}
                        for c in built["components"]],
        ))
        seen.append(built["name"])
    return offers


async def board(session: AsyncSession, user: User, *, meal_type: str | None = None,
                allow_build: bool = True) -> Board:
    """Собрать экран подбора для человека."""
    meal = meal_type or default_meal(user.timezone)
    if meal not in MEAL_CODES:
        meal = "lunch"

    budget, left, gap = await _budget_and_gap(session, user, meal)
    fitted, near = await dish_picker.pick_dishes(
        session, user, meal_type=meal, budget=budget, gap=gap, limit=WANTED)

    offers = [_from_pick(pick) for pick in fitted]
    approximate = False

    if len(offers) < WANTED and allow_build:
        offers += await _built_offers(
            session, user, meal_type=meal, budget=budget, gap=gap,
            avoid=[o.name for o in offers], count=WANTED - len(offers))

    if not offers and near:
        # Ничего точного нет — честно показываем ближайшее, а не выдумываем.
        offers = [_from_pick(pick) for pick in near]
        approximate = True
        for offer in offers:
            offer.approximate = True

    for offer in offers:
        if offer.components is None and offer.code:
            dish = next((p.dish for p in fitted + near if p.dish.code == offer.code), None)
            if dish is not None:
                offer.components = await dish_picker.components_of(session, dish, offer.scale)

    return Board(
        meal_type=meal, meal_name=MEAL_RU[meal], budget=int(budget),
        left_calories=int(left), gap=gap,
        hint=method.plate_hint(meal),
        offers=offers, approximate=approximate,
    )


__all__ = ["Board", "MEAL_CODES", "MEAL_RU", "Offer", "board", "default_meal"]
