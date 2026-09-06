"""Подбор блюда под остаток нормы человека.

Работает только по справочнику: ничего не выдумывает и никуда не ходит.
Порядок такой — сначала отсеиваем то, что человеку нельзя, потом подгоняем
порцию под бюджет приёма, потом сортируем по тому, насколько вариант
уместен именно сейчас.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Dish, DishComponent, Meal, Prep, Product, User
from services import method

logger = logging.getLogger(__name__)

# Насколько можно растянуть или ужать авторскую порцию. Шире — это уже
# другое блюдо, а не порция того же самого.
SCALE_MIN, SCALE_MAX = 0.7, 1.3
# Допуск по бюджету приёма после пересчёта порции.
BUDGET_TOLERANCE = 0.25
# Сколько дней подряд не повторять блюдо.
REPEAT_DAYS = 3

DIET_FIELD = {"vegan": "vegan", "vegetarian": "vegetarian", "gluten_free": "gluten_free"}


@dataclass
class Pick:
    """Готовый вариант: блюдо, пересчитанная порция и её КБЖУ."""

    dish: Dish
    scale: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float
    weight_g: float
    reason: str = ""
    components: list[tuple[str, float, str]] = field(default_factory=list)
    preps: list[str] = field(default_factory=list)

    @property
    def author(self) -> bool:
        return self.dish.author

    def to_dict(self) -> dict:
        return {
            "code": self.dish.code,
            "name": self.dish.name,
            "author": self.dish.author,
            "source": self.dish.source,
            "minutes": self.dish.minutes,
            "scale": round(self.scale, 2),
            "calories": round(self.kcal),
            "protein_g": round(self.protein_g, 1),
            "fat_g": round(self.fat_g, 1),
            "carbs_g": round(self.carbs_g, 1),
            "fiber_g": round(self.fiber_g, 1),
            "weight_g": round(self.weight_g),
            "reason": self.reason,
            "preps": self.preps,
        }


def _allergen_words(raw: str | None) -> set[str]:
    """Аллергии человек пишет свободным текстом — разбираем по словам."""
    if not raw:
        return set()
    cleaned = raw.lower().replace(",", " ").replace(";", " ").replace("/", " ")
    return {word.strip(".!") for word in cleaned.split() if len(word) > 2}


def _blocked(product: Product, words: set[str]) -> bool:
    """Продукт под запретом, если совпал с аллергией по названию или метке."""
    haystack = f"{product.name} {product.aliases} {product.allergens}".lower()
    return any(word in haystack for word in words)


def scale_for(dish: Dish, budget: float) -> float | None:
    """Коэффициент порции под бюджет приёма. None — блюдо не подходит."""
    if dish.kcal <= 0 or budget <= 0:
        return None
    raw = budget / dish.kcal
    scale = min(SCALE_MAX, max(SCALE_MIN, raw))
    # После зажима в границы проверяем, попали ли в допуск по калориям.
    if abs(dish.kcal * scale - budget) > budget * BUDGET_TOLERANCE:
        return None
    return round(scale, 2)


def _scaled(dish: Dish, scale: float) -> Pick:
    return Pick(
        dish=dish, scale=scale,
        kcal=dish.kcal * scale, protein_g=dish.protein_g * scale,
        fat_g=dish.fat_g * scale, carbs_g=dish.carbs_g * scale,
        fiber_g=dish.fiber_g * scale, weight_g=dish.weight_g * scale,
    )


async def _recent_codes(session: AsyncSession, user_id: int, days: int = REPEAT_DAYS) -> set[str]:
    """Что человек уже ел в последние дни — чтобы не предлагать то же самое."""
    since = datetime.utcnow() - timedelta(days=days)
    names = (await session.execute(
        select(Meal.name).where(Meal.user_id == user_id, Meal.logged_at >= since)
    )).scalars().all()
    return {name.strip().lower() for name in names}


async def candidates(session: AsyncSession, user: User, meal_type: str) -> list[Dish]:
    """Блюда, которые этому человеку в принципе можно показывать."""
    dishes = (await session.execute(
        select(Dish).where(Dish.meal_types.contains(meal_type))
    )).scalars().all()
    if not dishes:
        return []

    products = {p.code: p for p in (await session.execute(select(Product))).scalars()}
    components = (await session.execute(
        select(DishComponent).where(DishComponent.dish_id.in_([d.id for d in dishes]))
    )).scalars().all()

    by_dish: dict[int, list[DishComponent]] = {}
    for item in components:
        by_dish.setdefault(item.dish_id, []).append(item)

    words = _allergen_words(user.allergies)
    diet = user.diet_type.value if user.diet_type else "regular"
    diet_field = DIET_FIELD.get(diet)

    allowed: list[Dish] = []
    for dish in dishes:
        parts = by_dish.get(dish.id, [])
        ok = True
        for item in parts:
            product = products.get(item.product_code)
            if product is None:
                ok = False
                break
            if item.optional:
                continue
            if words and _blocked(product, words):
                ok = False
                break
            if diet_field and not getattr(product, diet_field):
                ok = False
                break
        if ok:
            allowed.append(dish)
    return allowed


def rank(picks: list[Pick], *, budget: float, gap: str | None,
         recent: set[str]) -> list[Pick]:
    """Отсортировать варианты: чем меньше счёт, тем уместнее сейчас."""
    def score(pick: Pick) -> float:
        value = abs(pick.kcal - budget) / max(budget, 1)
        # Закрыть главный недобор дня важнее, чем попасть в калории до единицы.
        if gap == "protein_g" and pick.protein_g >= 25:
            value -= 0.25
        if gap == "fiber_g" and pick.fiber_g >= 7:
            value -= 0.25
        # Её рецепт при прочих равных идёт выше: это ядро сервиса.
        if pick.dish.author:
            value -= 0.05
        if pick.dish.name.strip().lower() in recent:
            value += 0.5
        # Долгая готовка вечером — так себе предложение, а собранное из
        # заготовок наоборот: это её главный способ экономить время.
        value += min(pick.dish.minutes, 60) / 600
        if pick.preps:
            value -= 0.08
        return value

    return sorted(picks, key=score)


async def prep_names(session: AsyncSession, dish: Dish) -> list[str]:
    """Названия заготовок, из которых собирается блюдо."""
    codes = [code for code in (dish.prep_codes or "").split(";") if code]
    if not codes:
        return []
    rows = (await session.execute(select(Prep).where(Prep.code.in_(codes)))).scalars().all()
    order = {code: index for index, code in enumerate(codes)}
    return [prep.name for prep in sorted(rows, key=lambda p: order.get(p.code, 99))]


def explain(pick: Pick, *, budget: float, gap: str | None) -> str:
    """Одна фраза, чем вариант хорош именно сейчас."""
    if pick.preps and pick.dish.minutes <= 12:
        return f"Почти всё готово — собрать за {pick.dish.minutes} минут"
    if gap == "protein_g" and pick.protein_g >= 25:
        return f"Закроет недобор белка — {pick.protein_g:.0f} г"
    if gap == "fiber_g" and pick.fiber_g >= 7:
        return f"Много клетчатки — {pick.fiber_g:.0f} г"
    if abs(pick.kcal - budget) <= budget * 0.08:
        return f"Точно в бюджет приёма — {pick.kcal:.0f} ккал"
    if pick.dish.minutes <= 15:
        return f"Готовится {pick.dish.minutes} минут"
    return f"{pick.kcal:.0f} ккал на порцию"


async def pick_dishes(session: AsyncSession, user: User, *, meal_type: str,
                      budget: float, gap: str | None = None,
                      limit: int = 3) -> tuple[list[Pick], list[Pick]]:
    """Подобрать блюда под приём пищи.

    Возвращает (подошедшие, ближайшие). Второй список не пустой только когда
    первый пуст: это честный ответ «точного варианта нет, вот что рядом»
    вместо выдуманного блюда.
    """
    allowed = await candidates(session, user, meal_type)
    recent = await _recent_codes(session, user.id)

    fitted, near = [], []
    for dish in allowed:
        scale = scale_for(dish, budget)
        if scale is None:
            # Ближайшее — с зажатой в границы порцией, чтобы было что показать.
            fallback = min(SCALE_MAX, max(SCALE_MIN, budget / dish.kcal)) if dish.kcal else 1
            near.append(_scaled(dish, round(fallback, 2)))
            continue
        fitted.append(_scaled(dish, scale))

    for pick in fitted:
        pick.preps = await prep_names(session, pick.dish)

    ranked = rank(fitted, budget=budget, gap=gap, recent=recent)[:limit]
    for pick in ranked:
        pick.reason = explain(pick, budget=budget, gap=gap)

    if ranked:
        return ranked, []

    closest = sorted(near, key=lambda p: abs(p.kcal - budget))[:limit]
    for pick in closest:
        pick.preps = await prep_names(session, pick.dish)
        over = pick.kcal - budget
        pick.reason = (f"На {abs(over):.0f} ккал {'больше' if over > 0 else 'меньше'} "
                       f"бюджета приёма")
    return [], closest


async def components_of(session: AsyncSession, dish: Dish,
                        scale: float = 1.0) -> list[dict]:
    """Состав блюда на одну порцию с учётом пересчёта."""
    items = (await session.execute(
        select(DishComponent).where(DishComponent.dish_id == dish.id)
    )).scalars().all()
    products = {p.code: p for p in (await session.execute(select(Product))).scalars()}

    out: list[dict] = []
    for item in items:
        product = products.get(item.product_code)
        if product is None:
            continue
        grams = item.grams / (dish.portions or 1) * scale
        if item.countable and product.gram_per_piece:
            # Штуки округляем до целого: яйцо не бывает 1,4 штуки.
            pieces = max(1, round(grams / product.gram_per_piece))
            grams = pieces * product.gram_per_piece
        out.append({
            "name": product.name,
            "grams": round(grams) if not product.is_seasoning else 0,
            "raw": item.raw_amount,
            "seasoning": product.is_seasoning,
            "role": product.role,
        })
    return out


__all__ = ["BUDGET_TOLERANCE", "Pick", "REPEAT_DAYS", "SCALE_MAX", "SCALE_MIN",
           "candidates", "components_of", "explain", "pick_dishes", "prep_names",
           "rank", "scale_for"]
