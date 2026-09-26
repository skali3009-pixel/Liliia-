"""Аллергия — не слово в строке, а продукты, которых не должно быть на экране.

Проверено перебором на справочнике: из шестнадцати обычных формулировок
(«арахис», «яйца», «рыбу», «лактоза», «молочка»…) семь пропускали сам
аллерген — в кубике, в книге рецептов или в обоих. Хлеб «по желанию» при
глютене не проверялся вовсе: необязательный ингредиент пропускался мимо
фильтра. А сборка блюда моделью для человека с любой аллергией падала на
первом же продукте — в проверку уходил объект вместо строки.

Тесты гоняют настоящий справочник, а не выдуманные продукты: утечка
живёт именно в том, как названы и помечены реальные строки.
"""

import asyncio
import random

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, DietTypeEnum, Product, User
from services import allergens, cube, dish_picker

# Как пишут люди → метка справочника, которой быть не должно.
WRITTEN = {
    "орехи": "орехи", "орех": "орехи", "арахис": "орехи", "миндаль": "орехи",
    "на орехи": "орехи", "Орехи, мёд": "орехи",
    "яйца": "яйцо", "яйцо": "яйцо",
    "молоко": "молоко", "лактоза": "молоко", "молочка": "молоко",
    "рыба": "рыба", "рыбу": "рыба", "глютен": "глютен", "кунжут": "кунжут",
    "аллергия на мёд": "мёд",
}


def run(scenario):
    asyncio.run(scenario())


async def reference():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        from seed.nutrition.loader import seed_nutrition

        await seed_nutrition(session)
        products = {p.code: p for p in (await session.execute(select(Product))).scalars()}
    return engine, maker, products


def marked(product: Product, code: str) -> bool:
    return code in (product.allergens or "").split(";")


@pytest.mark.parametrize("written,code", WRITTEN.items(), ids=list(WRITTEN))
def test_recipes_never_offer_the_allergen(written, code):
    async def scenario():
        engine, maker, products = await reference()
        try:
            async with maker() as session:
                user = User(id=1, allergies=written, diet_type=DietTypeEnum.REGULAR)
                leaks = set()
                for meal in ("breakfast", "lunch", "dinner", "snack"):
                    for dish in await dish_picker.candidates(session, user, meal):
                        for item in dish.components:   # и необязательные тоже
                            product = products.get(item.product_code)
                            if product and marked(product, code):
                                leaks.add(f"{dish.name} ← {product.name}")
            assert not leaks, sorted(leaks)[:5]
        finally:
            await engine.dispose()
    run(scenario)


@pytest.mark.parametrize("written,code", WRITTEN.items(), ids=list(WRITTEN))
def test_the_cube_never_offers_the_allergen_nor_as_a_swap(written, code):
    async def scenario():
        engine, _, products = await reference()
        try:
            # Как в /api/cube: строка из анкеты режется по запятым.
            exclude = {part.strip().lower() for part in written.split(",") if part.strip()}
            rng = random.Random(7)
            leaks = set()
            for level in cube.LEVELS:
                for _ in range(10):
                    for item in cube.build(products, level=level, exclude=exclude, rng=rng):
                        shown = [part.code for part in item.items]
                        shown += [c for swaps in item.swaps.values() for c in swaps]
                        leaks |= {products[c].name for c in shown
                                  if c in products and marked(products[c], code)}
            assert not leaks, sorted(leaks)
        finally:
            await engine.dispose()
    run(scenario)


def test_the_filter_does_not_throw_away_a_pinch_of_spice():
    """Лишний запрет безопаснее пропущенного, но у всего есть мера: у
    «Специй» среди синонимов «мускатный орех», и при аллергии на орехи
    пропадали бы тридцать блюд со щепоткой перца."""
    rules = allergens.parse("орехи")
    assert not rules.blocks("специи перец мускатный орех", "", name="Специи")
    assert rules.blocks("ореховая паста", "", name="Ореховая паста")
    assert rules.blocks("кешью", "орехи", name="Кешью")


def test_unknown_words_are_searched_by_stem():
    rules = allergens.parse("клубнику, киви")
    assert rules.blocks("клубника свежая", "", name="Клубника")
    assert rules.blocks("киви", "", name="Киви")
    assert not rules.blocks("банан", "", name="Банан")


def test_no_allergies_means_no_rules():
    for empty in (None, "", "нет", "аллергии нет"):
        assert not allergens.parse(empty)


def test_the_dish_builder_survives_an_allergy():
    """Раньше `allowed_products` отдавала в проверку сам продукт вместо
    строки — сборка падала TypeError у любого человека с аллергией."""
    async def scenario():
        from services.dish_builder import allowed_products

        engine, _, products = await reference()
        try:
            allowed = allowed_products(list(products.values()), diet="regular",
                                       allergy_words=allergens.parse("арахис, рыбу"))
            assert allowed
            assert not [p.name for p in allowed if marked(p, "орехи") or marked(p, "рыба")]
        finally:
            await engine.dispose()
    run(scenario)
