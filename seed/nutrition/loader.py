"""Заливка справочника питания в базу и подсчёт КБЖУ блюд.

Считает арифметика, а не языковая модель: КБЖУ блюда — это сумма по составу,
делённая на число порций. Модель может предложить состав, но цифры всегда
приходят отсюда.

Повторный запуск ничего не дублирует: продукты и блюда обновляются по коду.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Dish, DishComponent, Product
from seed.nutrition.dishes import DISHES
from seed.nutrition.products import PRODUCTS

logger = logging.getLogger(__name__)


def nutrition_of(components: list[dict], products: dict[str, Product],
                 portions: float = 1.0) -> dict[str, float]:
    """КБЖУ и вес одной порции по составу блюда."""
    totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0,
              "carbs_g": 0.0, "fiber_g": 0.0, "weight_g": 0.0}
    for item in components:
        product = products.get(item["product_code"])
        if product is None or product.is_seasoning:
            continue
        grams = item["grams"]
        share = grams / 100
        totals["kcal"] += product.kcal * share
        totals["protein_g"] += product.protein * share
        totals["fat_g"] += product.fat * share
        totals["carbs_g"] += product.carbs * share
        totals["fiber_g"] += product.fiber * share
        # Вода в супе — вес есть, калорий нет: в порцию она входит честно.
        totals["weight_g"] += grams

    portions = portions or 1.0
    return {key: round(value / portions, 1) for key, value in totals.items()}


async def seed_nutrition(session: AsyncSession) -> tuple[int, int]:
    """Залить продукты и блюда. Возвращает (продуктов, блюд) записанных."""
    existing = {p.code: p for p in (await session.execute(select(Product))).scalars()}

    for data in PRODUCTS:
        product = existing.get(data["code"])
        if product is None:
            product = Product(**data)
            session.add(product)
            existing[data["code"]] = product
        else:
            for field, value in data.items():
                setattr(product, field, value)
    await session.commit()

    products = {p.code: p for p in (await session.execute(select(Product))).scalars()}
    dishes = {d.code: d for d in (await session.execute(select(Dish))).scalars()}

    for data in DISHES:
        components = data["components"]
        values = {k: v for k, v in data.items() if k != "components"}
        values.update(nutrition_of(components, products, data["portions"]))

        dish = dishes.get(data["code"])
        if dish is None:
            dish = Dish(**values)
            session.add(dish)
            await session.flush()
        else:
            for field, value in values.items():
                setattr(dish, field, value)
            # Состав переписываем целиком: так правка рецепта не оставляет хвостов.
            for old in list(dish.components):
                await session.delete(old)
            await session.flush()

        for item in components:
            session.add(DishComponent(dish_id=dish.id, **item))

    await session.commit()
    logger.info("Справочник питания: %d продуктов, %d блюд", len(PRODUCTS), len(DISHES))
    return len(PRODUCTS), len(DISHES)


__all__ = ["nutrition_of", "seed_nutrition"]
