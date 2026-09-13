"""Справочник питания в памяти.

Продукты, блюда и заготовки не меняются во время работы: они заливаются при
старте и дальше только читаются. Ходить за ними в базу на каждый запрос —
это три запроса и сотни строк на каждое нажатие «Подобрать блюдо».

Поэтому справочник читается один раз и лежит в памяти обычными объектами,
не привязанными к сессии базы. Заливка сбрасывает кэш, так что после
обновления бот покажет новые блюда, а не старые.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Dish, DishComponent, Prep, Product

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Component:
    """Продукт в блюде вместе со всем, что нужно для отбора и показа."""

    product_code: str
    grams: float
    raw_amount: str
    optional: bool
    countable: bool

    name: str
    role: str
    is_seasoning: bool
    gram_per_piece: float | None
    vegan: bool
    vegetarian: bool
    gluten_free: bool
    # Название, синонимы и аллергены одной строкой — по ней ищем запреты.
    haystack: str


@dataclass(frozen=True)
class CachedDish:
    """Блюдо со всеми полями, которые нужны подбору, без похода в базу."""

    id: int
    code: str
    name: str
    meal_types: tuple[str, ...]
    portions: float
    instructions: str
    notes: str
    minutes: int
    author: bool
    source: str
    estimated: bool
    no_cook: bool
    prep_codes: tuple[str, ...]
    prep_titles: tuple[str, ...]

    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float
    weight_g: float

    components: tuple[Component, ...] = field(default_factory=tuple)


_dishes: tuple[CachedDish, ...] | None = None
_by_code: dict[str, CachedDish] = {}
_products: dict[str, Product] | None = None


def reset() -> None:
    """Забыть кэш: справочник перезалили, значит данные устарели."""
    global _dishes, _products
    _dishes = None
    _products = None
    _by_code.clear()


async def products(session: AsyncSession) -> dict[str, Product]:
    """Все продукты по коду. Нужны быстрому подбору на каждое нажатие."""
    global _products
    if _products is None:
        _products = {p.code: p for p in
                     (await session.execute(select(Product))).scalars()}
    return _products


async def load(session: AsyncSession) -> tuple[CachedDish, ...]:
    """Прочитать справочник в память. Повторный вызов ничего не читает."""
    global _dishes
    if _dishes is not None:
        return _dishes

    products = {p.code: p for p in (await session.execute(select(Product))).scalars()}
    preps = {p.code: p.name for p in (await session.execute(select(Prep))).scalars()}
    rows = (await session.execute(select(Dish))).scalars().all()
    parts = (await session.execute(select(DishComponent))).scalars().all()

    by_dish: dict[int, list[DishComponent]] = {}
    for item in parts:
        by_dish.setdefault(item.dish_id, []).append(item)

    built: list[CachedDish] = []
    for dish in rows:
        components = []
        for item in by_dish.get(dish.id, []):
            product = products.get(item.product_code)
            if product is None:
                # Блюдо ссылается на продукт, которого нет: показывать такое
                # нельзя — КБЖУ будет неполным.
                logger.warning("Блюдо %s ссылается на неизвестный продукт %s",
                               dish.code, item.product_code)
                components = None
                break
            components.append(Component(
                product_code=item.product_code, grams=item.grams,
                raw_amount=item.raw_amount, optional=item.optional,
                countable=item.countable, name=product.name, role=product.role,
                is_seasoning=product.is_seasoning, gram_per_piece=product.gram_per_piece,
                vegan=product.vegan, vegetarian=product.vegetarian,
                gluten_free=product.gluten_free,
                haystack=f"{product.name} {product.aliases} {product.allergens}".lower(),
            ))
        if components is None:
            continue

        codes = tuple(c for c in (dish.prep_codes or "").split(";") if c)
        built.append(CachedDish(
            id=dish.id, code=dish.code, name=dish.name,
            meal_types=tuple(dish.meal_types.split(";")), portions=dish.portions or 1,
            instructions=dish.instructions, notes=dish.notes, minutes=dish.minutes,
            author=dish.author, source=dish.source, estimated=dish.estimated,
            no_cook=dish.no_cook, prep_codes=codes,
            prep_titles=tuple(preps[c] for c in codes if c in preps),
            kcal=dish.kcal, protein_g=dish.protein_g, fat_g=dish.fat_g,
            carbs_g=dish.carbs_g, fiber_g=dish.fiber_g, weight_g=dish.weight_g,
            components=tuple(components),
        ))

    _dishes = tuple(built)
    _by_code.clear()
    _by_code.update({d.code: d for d in _dishes})
    logger.info("Справочник в памяти: %d блюд", len(_dishes))
    return _dishes


async def for_meal(session: AsyncSession, meal_type: str) -> list[CachedDish]:
    return [d for d in await load(session) if meal_type in d.meal_types]


async def by_code(session: AsyncSession, code: str) -> CachedDish | None:
    await load(session)
    return _by_code.get(code)


__all__ = ["CachedDish", "Component", "by_code", "for_meal", "load", "reset"]
