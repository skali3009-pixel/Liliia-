"""Кубик: быстрый подбор еды из магазина.

Главная проверка здесь — прогон списка K001-K110, который составила
владелица. Если правило не принимает то, что в нём есть, сломано правило,
а не список.
"""

import random

import pytest

from models import Product
from seed.nutrition.cube_rules import (
    BASKET,
    CURATED,
    GROUP_INDEX,
    LEVELS,
    PORTIONS,
    PROTEIN_GROUPS,
    pairing_ok,
    slots_ok,
)
from seed.nutrition.products import PRODUCTS
from seed.nutrition.products_store import STORE_PRODUCTS, STORE_TAGS
from services import cube


@pytest.fixture(scope="module")
def catalogue() -> dict[str, Product]:
    """Справочник в памяти — тот же, что уезжает в базу."""
    rows: dict[str, Product] = {}
    for data in PRODUCTS + STORE_PRODUCTS:
        values = dict(data)
        values.setdefault("tags", "")
        rows[values["code"]] = Product(**values)
    for code, tags in STORE_TAGS.items():
        rows[code].tags = ";".join(tags)
    return rows


# --- Проверочный список владелицы -----------------------------------------

def test_every_curated_combination_is_made_of_known_products(catalogue):
    """Список ссылается только на то, что есть в справочнике."""
    for name, codes in CURATED:
        for code in codes:
            assert code in catalogue, f"{name}: нет продукта {code}"
            assert code in PORTIONS, f"{name}: не задана порция для {code}"


@pytest.mark.parametrize("name,codes", CURATED, ids=[n for n, _ in CURATED])
def test_the_rules_accept_the_owners_list(name, codes):
    """Правило, которое отвергает её же еду, — сломанное правило."""
    groups = [GROUP_INDEX[c] for c in codes]
    assert any(slots_ok(groups, level) for level in LEVELS), "не прошёл по составу"
    assert pairing_ok(list(codes)), "не прошёл по сочетаемости"


# --- Правило состава -------------------------------------------------------

@pytest.mark.parametrize("groups,level,why", [
    (["фрукт", "орехи"], "meal", "почти обед без белка"),
    (["мясо", "сыр"], "light", "два белка в лёгком перекусе"),
    (["мясо", "мясо", "мясо"], "meal", "три источника белка"),
    (["овощ", "овощ", "овощ"], "normal", "три овоща подряд"),
    (["мясо", "овощ", "овощ", "фрукт", "хруст", "орехи"], "meal", "слишком много всего"),
])
def test_nonsense_is_rejected_by_shape(groups, level, why):
    assert not slots_ok(groups, level), why


def test_a_snack_may_go_without_protein_but_a_meal_may_not():
    """Яблоко с орехами — честный способ дотерпеть, но не приём пищи."""
    assert slots_ok(["фрукт", "орехи"], "light")
    assert not slots_ok(["фрукт", "орехи"], "meal")


# --- Сочетаемость ----------------------------------------------------------

@pytest.mark.parametrize("codes,why", [
    (["protein_bar", "celery"], "батончик с сельдереем"),
    (["chicken_smoked", "cucumber", "dark_chocolate"], "курица с шоколадкой"),
    (["turkey_fillet", "apple", "grapes"], "мясо с двумя фруктами"),
    (["cottage_cheese", "seaweed"], "творог с морской капустой"),
    (["greek_yogurt", "olives"], "йогурт с оливками"),
    (["surimi", "berries"], "крабовое мясо с ягодами"),
    (["yogurt_drink", "lettuce"], "питьевой йогурт с листьями салата"),
])
def test_things_nobody_eats_are_rejected(codes, why):
    """Категории сошлись — это ещё не еда."""
    assert not pairing_ok(codes), why


@pytest.mark.parametrize("codes,why", [
    (["cheese_hard", "apple"], "сыр с яблоком"),
    (["greek_yogurt", "berries"], "йогурт с ягодами"),
    (["ayran", "cucumber"], "айран с огурцом"),
    (["kefir", "banana", "walnut"], "кефир с бананом и орехами"),
])
def test_normal_food_is_accepted(codes, why):
    assert pairing_ok(codes), why


# --- Сборка ----------------------------------------------------------------

def test_a_cube_is_assembled_for_every_hunger_level(catalogue):
    for level, (_, low, high, _, _, _) in LEVELS.items():
        cubes = cube.build(catalogue, level=level, rng=random.Random(1))
        assert cubes, f"ничего не собралось для режима {level}"
        for item in cubes:
            assert low * 0.85 <= item.kcal <= high * 1.15, (
                f"{level}: {item.kcal:.0f} ккал вне диапазона {low}-{high}")


def test_without_a_spoon_nothing_spoonable_is_offered(catalogue):
    """Она просила еду для машины, а не список с оговорками."""
    spoonable = {code for code, product in catalogue.items()
                 if "spoon" in product.tags.split(";")}
    assert spoonable, "в справочнике не размечены ложечные продукты"

    for level in LEVELS:
        for item in cube.build(catalogue, level=level, no_spoon=True,
                               rng=random.Random(3), limit=5):
            offered = {i.code for i in item.items}
            assert not offered & spoonable, f"предложено ложечное: {offered & spoonable}"


def test_a_meal_always_has_real_protein(catalogue):
    """«Почти нормальный приём пищи» без белка — не приём пищи."""
    for seed in range(5):
        for item in cube.build(catalogue, level="meal", rng=random.Random(seed), limit=5):
            assert item.protein_share >= cube.MIN_PROTEIN_SHARE


def test_every_set_has_a_source_of_protein_except_the_lightest(catalogue):
    for level in ("normal", "hungry", "meal"):
        for item in cube.build(catalogue, level=level, rng=random.Random(2), limit=5):
            groups = {i.group for i in item.items}
            assert groups & PROTEIN_GROUPS, f"{level}: набор без белка"


def test_allergies_and_diet_are_obeyed(catalogue):
    for item in cube.build(catalogue, level="normal", vegan=True,
                           exclude={"орехи"}, rng=random.Random(4), limit=5):
        for part in item.items:
            product = catalogue[part.code]
            assert product.vegan, f"{product.name} не веганский"
            assert "орехи" not in product.allergens


def test_recent_sets_are_not_repeated(catalogue):
    first = cube.build(catalogue, level="normal", rng=random.Random(5), limit=3)
    assert first
    again = cube.build(catalogue, level="normal", rng=random.Random(5), limit=3,
                       recent=[c.signature for c in first])
    assert not ({c.signature for c in again} & {c.signature for c in first})


# --- Как это выглядит ------------------------------------------------------

def test_calories_are_shown_as_a_range(catalogue):
    """Точность до килокалории была бы враньём: у каждой марки состав свой."""
    item = cube.build(catalogue, level="normal", rng=random.Random(6))[0]
    low, high = item.kcal_range
    assert low <= item.kcal <= high
    assert high - low == 50


def test_a_card_is_never_named_after_something_it_does_not_contain(catalogue):
    """Карточка «Банановая страховка» без банана — это ошибка, а не шутка."""
    for level in LEVELS:
        for seed in range(4):
            for item in cube.build(catalogue, level=level, rng=random.Random(seed),
                                   limit=5):
                codes = {i.code for i in item.items}
                if item.title == "Банановая страховка":
                    assert "banana" in codes
                if item.title == "Кефирный экспресс":
                    assert codes & {"kefir", "ryazhenka"}


def test_pieces_are_named_as_pieces(catalogue):
    """«1 шт.» понятнее, чем «120 г» — на полке берут штуку."""
    banana = catalogue["banana"]
    item = cube.Item("banana", banana.name, banana.gram_per_piece, "фрукт",
                     banana.gram_per_piece)
    assert item.measure.startswith("1 шт.")


def test_swaps_stay_inside_the_group(catalogue):
    """Замена индейки — курица или тунец, но не хлебцы."""
    for item in cube.build(catalogue, level="normal", rng=random.Random(8), limit=3):
        for code, alternatives in item.swaps.items():
            for other in alternatives:
                assert GROUP_INDEX[other] == GROUP_INDEX[code]
                assert other != code


def test_hunger_level_follows_from_what_is_left(catalogue):
    assert cube.level_for(150) == "light"
    assert cube.level_for(300) == "normal"
    assert cube.level_for(450) == "hungry"
    assert cube.level_for(2000) == "meal"
    assert cube.level_for(None) == "normal"


def test_three_offers_are_three_different_offers(catalogue):
    """Один и тот же белок трижды — это один вариант, показанный трижды."""
    for level in ("normal", "hungry", "meal"):
        for seed in range(4):
            cubes = cube.build(catalogue, level=level, rng=random.Random(seed), limit=3)
            proteins = [frozenset(i.code for i in c.items if i.group in PROTEIN_GROUPS)
                        for c in cubes]
            assert len(set(proteins)) == len(proteins), f"{level}: белок повторился"


# --- «Я уже в магазине» ----------------------------------------------------

def test_one_question_gives_three_different_answers(catalogue):
    """Человек стоит у полки: гонять его по кругу «покажи другое» нельзя."""
    offers = cube.shop_offers(catalogue, craving="salty", no_spoon=True,
                              rng=random.Random(1))
    assert len(offers) == 3
    assert [label for label, _ in offers] == list(cube.SHOP_LABELS)

    proteins = [frozenset(i.code for i in item.items if i.group in PROTEIN_GROUPS)
                for _, item in offers]
    assert len(set(proteins)) == 3, "три варианта на одном белке — это один вариант"


def test_the_simple_option_is_the_simplest(catalogue):
    """«Самый простой» — тот, за которым меньше всего бегать по магазину."""
    offers = dict(cube.shop_offers(catalogue, rng=random.Random(2), no_spoon=True))
    simple = offers[cube.SHOP_LABELS[0]]
    filling = offers[cube.SHOP_LABELS[1]]
    assert len(simple.items) <= len(filling.items)
    assert simple.kcal < filling.kcal


# --- Корзина ---------------------------------------------------------------

def test_only_what_is_already_in_the_basket_is_offered(catalogue):
    """Предлагать то, за чем надо вернуться, — не решать задачу человека."""
    basket = {"kefir", "banana", "walnut", "apple"}
    cubes = cube.build(catalogue, level="normal", basket=basket,
                       rng=random.Random(3), limit=5)
    assert cubes
    for item in cubes:
        assert {part.code for part in item.items} <= basket


def test_a_basket_without_protein_yields_nothing(catalogue):
    """Честнее ничего не предложить, чем выдать яблоко с орехами за обед."""
    assert cube.build(catalogue, level="meal", basket={"apple", "walnut"},
                      rng=random.Random(4)) == []


def test_the_basket_offers_only_things_from_the_catalogue(catalogue):
    codes = [code for _, items in BASKET for code in items]
    assert len(codes) == len(set(codes)), "продукт попал в корзину дважды"
    for code in codes:
        assert code in catalogue, f"в корзине нет такого продукта: {code}"
        assert code in GROUP_INDEX, f"{code} не входит ни в одну группу"


def test_the_basket_always_offers_a_source_of_protein(catalogue):
    """Иначе человек отметит полкорзины и получит пустой экран."""
    rows = {title: items for title, items in BASKET}
    assert {GROUP_INDEX[c] for c in rows["Белок"]} <= PROTEIN_GROUPS
    assert {GROUP_INDEX[c] for c in rows["Выпить"]} <= PROTEIN_GROUPS


# --- Кубик смотрит на день -------------------------------------------------

def test_a_fibre_gap_forces_a_vegetable_or_fruit(catalogue):
    """Клетчатку нечем добрать, кроме овоща или фрукта. Это не пожелание."""
    for seed in range(4):
        cubes = cube.build(catalogue, level="normal",
                           needs=frozenset({cube.NEED_FIBER}),
                           rng=random.Random(seed), limit=3)
        assert cubes
        for item in cubes:
            groups = {part.group for part in item.items}
            assert groups & {"фрукт", "овощ", "хруст", "орехи"}, \
                f"набор без источника клетчатки: {[p.name for p in item.items]}"


def test_a_protein_gap_pushes_protein_up(catalogue):
    """При недоборе белка наборы должны стать белковее."""
    plain = cube.build(catalogue, level="normal", rng=random.Random(1), limit=3)
    hungry_for_protein = cube.build(catalogue, level="normal",
                                    needs=frozenset({cube.NEED_PROTEIN}),
                                    rng=random.Random(1), limit=3)
    assert max(c.protein_g for c in hungry_for_protein) >= \
        max(c.protein_g for c in plain)


def test_an_impossible_need_does_not_leave_an_empty_screen(catalogue):
    """Пустой экран полезен человеку меньше, чем набор без клетчатки."""
    # В корзине только йогурт и гранола — ни овоща, ни фрукта.
    basket = {"greek_yogurt", "granola"}
    assert not cube.build(catalogue, level="normal", basket=basket,
                          needs=frozenset({cube.NEED_FIBER}), rng=random.Random(2),
                          _no_fallback=True), "проверка бессмысленна: набор собрался"

    cubes = cube.build(catalogue, level="normal", basket=basket,
                       needs=frozenset({cube.NEED_FIBER}), rng=random.Random(2))
    assert cubes, "требование клетчатки оставило человека ни с чем"
