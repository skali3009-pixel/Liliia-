"""Подбор блюда: справочник, метод Анастасии и движок выдачи."""

import asyncio
import contextlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (ActivityLevelEnum, Base, Dish, DietTypeEnum, GenderEnum, GoalEnum,
                    Product, User)
from seed.nutrition.dishes import DISHES
from seed.nutrition.loader import nutrition_of, seed_nutrition
from seed.nutrition.products import BY_CODE, PRODUCTS
from services import dish_picker, method
from services.dish_builder import validate
from services.food_vision import FoodRecognitionError
from services.menu import board


@contextlib.asynccontextmanager
async def db(**overrides):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        await seed_nutrition(session)
        fields = dict(
            id=1, gender=GenderEnum.FEMALE, age=34, height_cm=165.0,
            current_weight_kg=70.0, target_weight_kg=62.0,
            activity_level=ActivityLevelEnum.MODERATE, goal=GoalEnum.LOSE_WEIGHT,
            diet_type=DietTypeEnum.REGULAR, timezone="Europe/Moscow",
            onboarding_completed=True, daily_calories=1600, daily_protein_g=120,
            daily_fat_g=48, daily_carbs_g=160, daily_fiber_g=22, daily_water_ml=2100,
        )
        fields.update(overrides)
        user = User(**fields)
        session.add(user)
        await session.commit()
        yield session, user
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


# --- справочник -----------------------------------------------------------

def test_every_dish_is_built_from_known_products():
    """Опечатка в коде продукта не должна доезжать до человека."""
    unknown = {c["product_code"] for d in DISHES for c in d["components"]} - set(BY_CODE)
    assert not unknown


def test_product_codes_are_unique():
    assert len(BY_CODE) == len(PRODUCTS)


def test_seeding_twice_does_not_duplicate():
    async def scenario():
        async with db() as (session, _):
            await seed_nutrition(session)
            dishes = (await session.execute(select(Dish))).scalars().all()
            assert len(dishes) == len(DISHES)
    run(scenario)


def test_calories_are_counted_from_the_composition():
    """Считает арифметика: 100 г творога 5% — это ровно 121 ккал."""
    products = {code: Product(**data) for code, data in BY_CODE.items()}
    totals = nutrition_of([{"product_code": "cottage_cheese", "grams": 100}], products)
    assert totals["kcal"] == 121.0
    assert totals["protein_g"] == 17.2


def test_seasonings_do_not_add_calories():
    """Соль и специи в составе есть, в подсчёте — нет."""
    products = {code: Product(**data) for code, data in BY_CODE.items()}
    with_salt = nutrition_of([{"product_code": "egg", "grams": 100},
                              {"product_code": "salt", "grams": 5},
                              {"product_code": "spices", "grams": 3}], products)
    plain = nutrition_of([{"product_code": "egg", "grams": 100}], products)
    assert with_salt["kcal"] == plain["kcal"]


def test_portions_are_divided_not_summed():
    """Состав на двоих не должен показываться как одна порция."""
    products = {code: Product(**data) for code, data in BY_CODE.items()}
    whole = nutrition_of([{"product_code": "chicken_fillet", "grams": 200}], products)
    half = nutrition_of([{"product_code": "chicken_fillet", "grams": 200}], products,
                        portions=2)
    assert half["kcal"] == pytest.approx(whole["kcal"] / 2, abs=0.2)


def test_every_dish_has_sane_numbers():
    """Ни одно блюдо не должно уйти в базу с нулём или тысячей ккал на порцию."""
    async def scenario():
        async with db() as (session, _):
            for dish in (await session.execute(select(Dish))).scalars():
                assert 80 <= dish.kcal <= 900, f"{dish.name}: {dish.kcal}"
                assert dish.weight_g > 0
    run(scenario)


# --- метод ----------------------------------------------------------------

def test_method_requires_protein_in_every_meal():
    problems = method.check(meal_type="lunch", kcal=400, protein_g=3,
                            components=[{"role": "крупа", "grams": 70},
                                        {"role": "овощи", "grams": 200}])
    assert any(p.rule == "белок" for p in problems)


def test_method_requires_vegetables_at_lunch_and_dinner():
    problems = method.check(meal_type="dinner", kcal=400, protein_g=35,
                            components=[{"role": "белок", "grams": 150},
                                        {"role": "овощи", "grams": 20}])
    assert any(p.rule == "овощи" for p in problems)


def test_method_keeps_a_snack_a_snack():
    """Перекус на 600 ккал — это уже обед, а не перекус."""
    problems = method.check(meal_type="snack", kcal=600, protein_g=20, components=[])
    assert any(p.rule == "перекус" for p in problems)


def test_a_correct_plate_passes():
    problems = method.check(meal_type="lunch", kcal=500, protein_g=40,
                            components=[{"role": "белок", "grams": 150},
                                        {"role": "крупа", "grams": 70},
                                        {"role": "овощи", "grams": 250},
                                        {"role": "жир", "grams": 15}])
    assert problems == []


def test_her_own_dishes_pass_her_own_rules():
    """Проверка бессмысленна, если её собственные рецепты её же и нарушают."""
    async def scenario():
        async with db() as (session, _):
            for dish in (await session.execute(select(Dish))).scalars():
                parts = await dish_picker.components_of(session, dish)
                for meal in dish.meal_types.split(";"):
                    problems = method.check(
                        meal_type=meal,
                        components=[{"role": p["role"], "grams": p["grams"]}
                                    for p in parts],
                        kcal=dish.kcal, protein_g=dish.protein_g)
                    assert not problems, f"{dish.name} [{meal}]: {problems}"
    run(scenario)


# --- подбор ---------------------------------------------------------------

def test_only_dishes_for_the_asked_meal_are_offered():
    async def scenario():
        async with db() as (session, user):
            for meal in ("breakfast", "lunch", "dinner", "snack"):
                for dish in await dish_picker.candidates(session, user, meal):
                    assert meal in dish.meal_types
    run(scenario)


def test_allergies_remove_dishes_by_composition_not_by_name():
    """«Салат с тунцом» не содержит слова «рыба» — отсеять его должен состав."""
    async def scenario():
        async with db(allergies="рыба") as (session, user):
            names = {d.name for d in await dish_picker.candidates(session, user, "dinner")}
            assert "Салат с тунцом и белой фасолью" not in names
            assert "Рыба в томатном соусе с булгуром" not in names
    run(scenario)


def test_a_vegan_is_never_offered_meat():
    async def scenario():
        async with db(diet_type=DietTypeEnum.VEGAN) as (session, user):
            for meal in ("breakfast", "lunch", "dinner", "snack"):
                for dish in await dish_picker.candidates(session, user, meal):
                    parts = await dish_picker.components_of(session, dish)
                    assert all(p["role"] != "белок" or "фасол" in p["name"].lower()
                               or "чечевиц" in p["name"].lower() or "нут" in p["name"].lower()
                               for p in parts), dish.name
    run(scenario)


def test_portion_scaling_stays_inside_sane_limits():
    dish = Dish(code="x", name="Тест", meal_types="lunch", kcal=500)
    assert dish_picker.scale_for(dish, 500) == 1.0
    assert dish_picker.scale_for(dish, 400) == 0.8
    # Втрое ужать блюдо нельзя — это уже не порция, а другое блюдо.
    assert dish_picker.scale_for(dish, 150) is None
    assert dish_picker.scale_for(dish, 2000) is None


def test_countable_products_are_rounded_to_whole_pieces():
    """Яйцо не бывает 1,4 штуки."""
    async def scenario():
        async with db() as (session, _):
            dish = (await session.execute(
                select(Dish).where(Dish.code == "w1d1_breakfast"))).scalar_one()
            parts = await dish_picker.components_of(session, dish, scale=0.7)
            egg = next(p for p in parts if p["name"].startswith("Яйцо"))
            assert egg["grams"] % 50 == 0
    run(scenario)


def test_a_protein_gap_lifts_protein_rich_dishes():
    async def scenario():
        async with db() as (session, user):
            fitted, _ = await dish_picker.pick_dishes(
                session, user, meal_type="lunch", budget=520, gap="protein_g")
            assert fitted and fitted[0].protein_g >= 25
    run(scenario)


def test_when_nothing_fits_we_show_the_closest_not_a_made_up_dish():
    async def scenario():
        async with db() as (session, user):
            fitted, near = await dish_picker.pick_dishes(
                session, user, meal_type="lunch", budget=90)
            assert not fitted
            assert near, "должно быть хотя бы ближайшее"
            assert all(p.dish.code for p in near), "ближайшее — из справочника"
    run(scenario)


# --- сборка сверх меню ----------------------------------------------------

def test_a_product_outside_the_list_is_refused():
    """Главная защита: модель не может подсунуть то, чего нет в справочнике."""
    products = {code: Product(**data) for code, data in BY_CODE.items()}
    with pytest.raises(FoodRecognitionError):
        validate({"components": [{"code": "фуа-гра", "grams": 100}]},
                 products, meal_type="lunch")


def test_an_implausible_weight_is_refused():
    products = {code: Product(**data) for code, data in BY_CODE.items()}
    with pytest.raises(FoodRecognitionError):
        validate({"components": [{"code": "chicken_fillet", "grams": 5000}]},
                 products, meal_type="lunch")


def test_calories_come_from_our_table_even_if_the_model_sends_its_own():
    """Модель прислала «200 ккал» — считаем всё равно мы: 150 г курицы это 170."""
    from services.dish_builder import nutrition

    products = {code: Product(**data) for code, data in BY_CODE.items()}
    components, _ = validate(
        {"calories": 200, "components": [
            {"code": "chicken_fillet", "grams": 150},
            {"code": "buckwheat", "grams": 70},
            {"code": "tomato", "grams": 150},
            {"code": "olive_oil", "grams": 10}]},
        products, meal_type="lunch")
    totals = nutrition(components, products)
    assert totals["kcal"] == pytest.approx(169.5 + 215.6 + 30 + 89.8, abs=1)


def test_a_composition_breaking_the_method_is_reported():
    products = {code: Product(**data) for code, data in BY_CODE.items()}
    _, problems = validate(
        {"components": [{"code": "rice", "grams": 90}, {"code": "olive_oil", "grams": 20}]},
        products, meal_type="lunch")
    assert problems, "рис с маслом без белка и овощей не должен проходить"


# --- экран ----------------------------------------------------------------

def test_board_gives_the_screen_everything_it_needs():
    async def scenario():
        async with db() as (session, user):
            result = await board(session, user, meal_type="lunch", allow_build=False)
            assert result.meal_name == "обед"
            assert result.budget > 0
            assert result.hint
            assert 1 <= len(result.offers) <= 3
            first = result.offers[0].to_dict()
            assert first["calories"] > 0 and first["components"]
    run(scenario)


def test_offers_from_her_menu_are_marked_and_others_are_not():
    async def scenario():
        async with db() as (session, user):
            result = await board(session, user, meal_type="breakfast", allow_build=False)
            assert all(o.author and o.source for o in result.offers)
    run(scenario)


def test_the_meal_is_guessed_but_can_be_asked_for():
    async def scenario():
        async with db() as (session, user):
            result = await board(session, user, meal_type="snack", allow_build=False)
            assert result.meal_type == "snack"
            assert all(o.calories <= method.SNACK_MAX_KCAL for o in result.offers)
    run(scenario)


# --- полный цикл сборки с подставной моделью ------------------------------

class _Block:
    type = "tool_use"
    name = "build_dish"

    def __init__(self, payload):
        self.input = payload


class _Response:
    def __init__(self, payload):
        self.content = [_Block(payload)]


class _FakeClient:
    """Модель, которая отвечает заранее заданными составами."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []
        self.messages = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return _Response(self.payloads.pop(0))


def _use(monkeypatch, client):
    import services.dish_builder as builder

    monkeypatch.setattr(builder, "get_client", lambda: client)
    return builder


def test_a_built_dish_gets_its_calories_from_our_table(monkeypatch):
    """Модель прислала состав — цифры посчитали мы, и они сходятся."""
    client = _FakeClient({
        "name": "Курица с гречкой и овощами", "minutes": 25,
        "instructions": "Отварить гречку, запечь курицу, собрать тарелку.",
        "components": [
            {"code": "chicken_fillet", "grams": 150},
            {"code": "buckwheat", "grams": 70},
            {"code": "tomato", "grams": 120},
            {"code": "cucumber", "grams": 100},
            {"code": "olive_oil", "grams": 10},
        ],
    })
    builder = _use(monkeypatch, client)

    async def scenario():
        async with db() as (session, user):
            products = list((await session.execute(select(Product))).scalars())
            built = await builder.build_dish(user, meal_type="lunch", budget=520,
                                             products=products)
            assert built["name"] == "Курица с гречкой и овощами"
            # 150 г курицы + 70 г гречки + 120 г помидоров + 100 г огурца + 10 г масла
            assert built["kcal"] == pytest.approx(513.9, abs=1)
            assert built["protein_g"] == pytest.approx(46.3, abs=0.5)
    run(scenario)


def test_the_model_only_sees_products_it_is_allowed_to_use(monkeypatch):
    """Вегану список продуктов приходит уже без мяса — соблазна нет."""
    client = _FakeClient({
        "name": "Чечевица с овощами", "minutes": 25, "instructions": "Смешать.",
        "components": [{"code": "lentils_dry", "grams": 80},
                       {"code": "eggplant", "grams": 150},
                       {"code": "tomato", "grams": 150},
                       {"code": "olive_oil", "grams": 10}],
    })
    builder = _use(monkeypatch, client)

    async def scenario():
        async with db(diet_type=DietTypeEnum.VEGAN) as (session, user):
            products = list((await session.execute(select(Product))).scalars())
            await builder.build_dish(user, meal_type="lunch", budget=520,
                                     products=products)
            request = client.requests[0]["messages"][0]["content"]
            assert "chicken_fillet" not in request
            assert "cottage_cheese" not in request
            assert "lentils_dry" in request
    run(scenario)


def test_a_dish_breaking_the_method_is_rebuilt_not_shown(monkeypatch):
    """Первый ответ без белка и овощей — модель просят собрать заново."""
    client = _FakeClient(
        {"name": "Каша на масле", "minutes": 10, "instructions": "Сварить.",
         "components": [{"code": "rice", "grams": 90}, {"code": "olive_oil", "grams": 15}]},
        {"name": "Индейка с чечевицей и овощами", "minutes": 30, "instructions": "Тушить.",
         "components": [{"code": "turkey_fillet", "grams": 150},
                        {"code": "lentils_dry", "grams": 60},
                        {"code": "tomato", "grams": 150},
                        {"code": "zucchini", "grams": 100},
                        {"code": "olive_oil", "grams": 10}]},
    )
    builder = _use(monkeypatch, client)

    async def scenario():
        async with db() as (session, user):
            products = list((await session.execute(select(Product))).scalars())
            built = await builder.build_dish(user, meal_type="lunch", budget=520,
                                             products=products)
            assert built["name"] == "Индейка с чечевицей и овощами"
            # Во второй запрос ушло объяснение, что было не так.
            assert "нарушила правила" in client.requests[1]["messages"][0]["content"]
    run(scenario)


def test_an_invented_product_kills_the_whole_dish(monkeypatch):
    """Если модель тянет продукт из интернета — блюдо не показывается вообще."""
    payload = {"name": "Салат с фуа-гра", "minutes": 10, "instructions": "Собрать.",
               "components": [{"code": "foie_gras", "grams": 80},
                              {"code": "tomato", "grams": 150}]}
    client = _FakeClient(payload, payload)
    builder = _use(monkeypatch, client)

    async def scenario():
        async with db() as (session, user):
            products = list((await session.execute(select(Product))).scalars())
            with pytest.raises(FoodRecognitionError):
                await builder.build_dish(user, meal_type="lunch", budget=520,
                                         products=products)
    run(scenario)


def test_a_vegan_gets_a_built_dish_when_her_menu_has_none(monkeypatch):
    """Ради этого сборка и нужна: в её меню веганского обеда нет."""
    client = _FakeClient({
        "name": "Чечевица с баклажаном", "minutes": 30, "instructions": "Тушить 20 минут.",
        "components": [{"code": "lentils_dry", "grams": 80},
                       {"code": "eggplant", "grams": 150},
                       {"code": "tomato", "grams": 150},
                       {"code": "spinach", "grams": 40},
                       {"code": "olive_oil", "grams": 10}],
    })
    _use(monkeypatch, client)

    async def scenario():
        async with db(diet_type=DietTypeEnum.VEGAN) as (session, user):
            catalogue_only = await board(session, user, meal_type="lunch",
                                         allow_build=False)
            assert not catalogue_only.offers or catalogue_only.approximate

            result = await board(session, user, meal_type="lunch", allow_build=True)
            assert result.offers
            built = result.offers[0]
            assert built.name == "Чечевица с баклажаном"
            # Блюдо сверх меню не помечается автором — так решила владелица.
            assert built.author is False and built.source == ""
            assert built.calories > 0
    run(scenario)
