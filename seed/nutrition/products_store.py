"""Магазинные продукты: то, что покупают готовым и едят сразу.

Отдельно от products.py намеренно. Тот справочник ограничен списками
покупок Анастасии — всё, что бот предлагает готовить, собирается только
оттуда. Здесь другое: ряженка, хлебцы, протеиновый коктейль и сырные
палочки в её меню не встречаются, но именно они стоят на полке, когда
готовить негде.

Откуда цифры. Часть — из тех же таблиц химического состава (ряженка,
моцарелла, тофу). Часть — усреднённые значения с этикеток российских
марок: у протеинового батончика или гранолы «справочного» состава не
бывает, он у каждого производителя свой. Поэтому такие продукты помечены
приблизительными и показываются диапазоном, а не точным числом: врать
точностью хуже, чем честно сказать «примерно».

Теги — только то, чего не видно из остальных полей:
    spoon      нужна ложка или вилка
    no_spoon   едят руками или пьют
    portable   не течёт и не крошится, годится в дорогу
    drink      это напиток
    budget     дешёвое
    sweet      сладкий вкус
    salty      солёный вкус
    crunchy    хрустит
    ready      готово к еде, ничего не делать
"""

from __future__ import annotations

from seed.nutrition.products import F, J, K, M, O, P, V

STORE_PRODUCTS: list[dict] = []


def _add(code, name, aliases, category, role, kcal, protein, fat, carbs, fiber,
         *, tags, piece=None, vegan=False, vegetarian=True, gluten_free=True,
         allergens=""):
    STORE_PRODUCTS.append(dict(
        code=code, name=name, aliases=aliases, category=category, role=role,
        kcal=kcal, protein=protein, fat=fat, carbs=carbs, fiber=fiber,
        gram_per_piece=piece, is_seasoning=False, vegan=vegan,
        vegetarian=vegetarian, gluten_free=gluten_free, allergens=allergens,
        tags=";".join(tags),
    ))


# --- Кисломолочное питьё: открыл и выпил ----------------------------------
_add("ryazhenka", "Ряженка", "ряженка", "молочное", M, 54, 2.9, 2.5, 4.2, 0,
     tags=["drink", "no_spoon", "portable", "sweet", "ready", "budget"],
     allergens="молоко")
_add("ayran", "Айран", "айран", "молочное", M, 35, 1.7, 1.5, 3.5, 0,
     tags=["drink", "no_spoon", "portable", "salty", "ready"], allergens="молоко")
_add("tan", "Тан", "тан", "молочное", M, 24, 1.1, 0.9, 2.6, 0,
     tags=["drink", "no_spoon", "portable", "salty", "ready"], allergens="молоко")
_add("yogurt_drink", "Питьевой йогурт натуральный", "питьевой йогурт", "молочное", P,
     60, 4.3, 2.0, 6.0, 0,
     tags=["drink", "no_spoon", "portable", "sweet", "ready"], allergens="молоко")
_add("yogurt_greek_drink", "Греческий питьевой йогурт", "теос;эпика;питьевой греческий",
     "молочное", P, 73, 9.0, 2.0, 3.6, 0,
     tags=["drink", "no_spoon", "portable", "sweet", "ready"], allergens="молоко")
_add("yogurt_high_protein", "Высокобелковый йогурт", "белковый йогурт;протеиновый йогурт",
     "молочное", P, 60, 10.0, 0.2, 4.5, 0,
     tags=["spoon", "sweet", "ready"], allergens="молоко")
_add("protein_shake", "Протеиновый коктейль", "протеиновый коктейль;милкшейк",
     "молочное", P, 55, 10.0, 1.0, 2.5, 0,
     tags=["drink", "no_spoon", "portable", "sweet", "ready"], allergens="молоко")
_add("protein_pudding", "Протеиновый пудинг", "протеиновый пудинг", "молочное", P,
     85, 9.0, 2.5, 6.0, 0, tags=["spoon", "sweet", "ready"], allergens="молоко")

# --- Сыры: берутся рукой --------------------------------------------------
_add("mozzarella", "Моцарелла", "моцарелла", "молочное", P, 240, 18.0, 18.0, 1.0, 0,
     tags=["salty", "ready"], allergens="молоко")
_add("mozzarella_mini", "Мини-моцарелла", "мини-моцарелла;черри-моцарелла",
     "молочное", P, 240, 18.0, 18.0, 1.0, 0,
     tags=["no_spoon", "portable", "salty", "ready"], allergens="молоко")
_add("cheese_adyghe", "Адыгейский сыр", "адыгейский сыр;сулугуни", "молочное", P,
     240, 19.0, 18.0, 1.5, 0, tags=["salty", "ready"], allergens="молоко")
_add("cheese_sticks", "Сырные палочки", "сырные палочки;чечил;косичка", "молочное", P,
     300, 24.0, 22.0, 2.0, 0,
     tags=["no_spoon", "portable", "salty", "ready"], allergens="молоко")

# --- Белок, который едят руками -------------------------------------------
_add("surimi", "Крабовое мясо", "сурими;крабовые палочки;крабовое мясо", "белок", P,
     95, 9.0, 1.0, 12.0, 0,
     tags=["no_spoon", "portable", "salty", "ready"], vegetarian=False,
     gluten_free=False, allergens="морепродукты;глютен")
_add("hummus", "Хумус", "хумус", "белок", P, 230, 7.5, 17.0, 12.0, 6.0,
     tags=["spoon", "salty", "ready"], vegan=True, allergens="кунжут")
_add("tofu", "Тофу", "тофу;тофу копчёный", "белок", P, 145, 15.0, 8.5, 2.0, 1.0,
     tags=["salty", "ready"], vegan=True, allergens="соя")

_add("protein_bar", "Протеиновый батончик", "протеиновый батончик;батончик",
     "белок", P, 360, 33.0, 12.0, 30.0, 4.0, piece=60,
     tags=["no_spoon", "portable", "sweet", "ready"], allergens="молоко;орехи")

# --- Фрукты, которые чистятся руками --------------------------------------
_add("mandarin", "Мандарин", "мандарин;мандарины", "фрукты", F, 38, 0.8, 0.2, 7.5, 1.8,
     piece=90, tags=["no_spoon", "portable", "sweet", "ready", "budget"], vegan=True)
_add("nectarine", "Нектарин", "нектарин", "фрукты", F, 44, 1.1, 0.3, 9.2, 1.7,
     piece=140, tags=["no_spoon", "portable", "sweet", "ready"], vegan=True)
_add("peach", "Персик", "персик", "фрукты", F, 39, 0.9, 0.1, 9.5, 2.1,
     piece=150, tags=["no_spoon", "sweet", "ready"], vegan=True)
_add("plum", "Слива", "слива;сливы", "фрукты", F, 42, 0.8, 0.3, 9.6, 1.5,
     piece=40, tags=["no_spoon", "portable", "sweet", "ready"], vegan=True)
_add("grapes", "Виноград", "виноград", "фрукты", F, 65, 0.6, 0.2, 15.0, 1.6,
     tags=["no_spoon", "portable", "sweet", "ready"], vegan=True)
_add("fruit_puree", "Фруктовое пюре в пакетике", "пюре;фруктовое пюре;паучи",
     "фрукты", F, 60, 0.4, 0.2, 13.5, 1.2,
     tags=["no_spoon", "portable", "sweet", "ready"], vegan=True)

# --- Овощи, которые грызут -------------------------------------------------
_add("veg_platter", "Овощная нарезка готовая", "овощная нарезка;нарезка овощей",
     "овощи", V, 22, 1.0, 0.2, 4.0, 1.4,
     tags=["no_spoon", "crunchy", "ready"], vegan=True)
_add("jerky", "Джерки", "джерки;вяленое мясо;мясные снеки", "белок", P,
     250, 45.0, 5.0, 5.0, 0,
     piece=50, tags=["no_spoon", "portable", "salty", "ready"], vegetarian=False)

_add("celery", "Стебель сельдерея", "сельдерей;черешковый сельдерей", "овощи", V,
     16, 0.9, 0.2, 2.1, 1.8,
     tags=["no_spoon", "crunchy", "ready"], vegan=True)
_add("seaweed", "Морская капуста", "морская капуста;ламинария", "овощи", V,
     25, 0.9, 0.2, 3.0, 0.6, tags=["salty", "ready"], vegan=True)

# --- Хруст -----------------------------------------------------------------
_add("crispbread", "Хлебцы цельнозерновые", "хлебцы", "крупы", K,
     360, 11.0, 3.0, 68.0, 6.0,
     tags=["no_spoon", "portable", "crunchy", "ready", "budget"], vegan=True,
     gluten_free=False, allergens="глютен")
_add("crispbread_rye", "Ржаные хлебцы", "ржаные хлебцы;гречневые хлебцы", "крупы", K,
     310, 12.6, 3.3, 57.1, 15.0,
     tags=["no_spoon", "portable", "crunchy", "ready", "budget"], vegan=True,
     gluten_free=False, allergens="глютен")
_add("crackers", "Несладкие крекеры", "крекеры", "крупы", K, 420, 9.0, 12.0, 68.0, 3.0,
     tags=["no_spoon", "portable", "crunchy", "salty", "ready"], vegan=True,
     gluten_free=False, allergens="глютен")
_add("galette", "Галеты", "галеты;хлебцы рисовые;рисовые вафли", "крупы", K,
     380, 8.0, 3.0, 78.0, 2.0,
     tags=["no_spoon", "portable", "crunchy", "ready", "budget"], vegan=True,
     gluten_free=False, allergens="глютен")
_add("bun_wholegrain", "Цельнозерновая булочка", "булочка;булка цельнозерновая",
     "крупы", K, 245, 9.0, 4.0, 42.0, 5.0, piece=70,
     tags=["no_spoon", "portable", "ready"], vegan=True,
     gluten_free=False, allergens="глютен")
_add("pita", "Пита", "пита;питa;хлебный кармашек", "крупы", K, 275, 9.1, 1.2, 55.7, 2.2,
     piece=60, tags=["no_spoon", "portable", "ready"], vegan=True,
     gluten_free=False, allergens="глютен")

# --- Сладкий хруст: честно помечен сладким --------------------------------
_add("granola", "Гранола", "гранола;мюсли", "крупы", K, 430, 9.0, 15.0, 62.0, 6.0,
     tags=["crunchy", "sweet", "spoon", "ready"], vegan=True,
     gluten_free=False, allergens="глютен")
_add("cereal_bar", "Фруктово-злаковый батончик", "злаковый батончик;мюсли батончик",
     "крупы", K, 420, 6.0, 15.0, 62.0, 4.0, piece=40,
     tags=["no_spoon", "portable", "sweet", "ready"], vegan=True,
     gluten_free=False, allergens="глютен")

# --- Орехи и семечки ------------------------------------------------------
_add("pistachio", "Фисташки", "фисташки", "орехи", J, 560, 20.0, 45.3, 16.4, 10.3,
     tags=["no_spoon", "portable", "crunchy", "salty", "ready"], vegan=True,
     allergens="орехи")
_add("pumpkin_seeds", "Тыквенные семечки", "тыквенные семечки;семечки", "орехи", J,
     556, 24.5, 45.8, 4.7, 6.0,
     tags=["no_spoon", "portable", "crunchy", "ready"], vegan=True)
_add("nut_mix", "Смесь орехов", "смесь орехов;ореховая смесь", "орехи", J,
     600, 18.0, 52.0, 15.0, 8.0,
     tags=["no_spoon", "portable", "crunchy", "ready"], vegan=True, allergens="орехи")

# Те же признаки для продуктов, которые уже есть в справочнике Анастасии.
# Дописываем их отдельно, чтобы не трогать сам справочник: он про её меню,
# а «нужна ли ложка» — вопрос этой функции, а не её.
STORE_TAGS: dict[str, list[str]] = {
    # Молочное и белок
    "kefir":           ["drink", "no_spoon", "portable", "ready", "budget"],
    "milk":            ["drink", "no_spoon", "portable", "sweet", "ready", "budget"],
    "greek_yogurt":    ["spoon", "sweet", "ready"],
    "yogurt":          ["spoon", "sweet", "ready", "budget"],
    "cottage_cheese":  ["spoon", "sweet", "ready", "budget"],
    "cheese_hard":     ["no_spoon", "portable", "salty", "ready"],
    "feta":            ["salty", "ready"],
    "egg":             ["no_spoon", "portable", "salty", "ready", "budget"],
    # Мясо и рыба, которые продаются готовыми
    "chicken_smoked":  ["no_spoon", "salty", "ready"],
    "turkey_fillet":   ["no_spoon", "salty", "ready"],
    "pastrami":        ["no_spoon", "portable", "salty", "ready"],
    "ham":             ["no_spoon", "portable", "salty", "ready"],
    "tuna_canned":     ["spoon", "salty", "ready"],
    "salmon_salted":   ["no_spoon", "salty", "ready"],
    # Фрукты
    "banana":          ["no_spoon", "portable", "sweet", "ready", "budget"],
    "apple":           ["no_spoon", "portable", "sweet", "crunchy", "ready", "budget"],
    "pear":            ["no_spoon", "portable", "sweet", "ready"],
    "orange":          ["no_spoon", "sweet", "ready"],
    "berries":         ["no_spoon", "sweet", "ready"],
    "kiwi":            ["spoon", "sweet", "ready"],
    "dates":           ["no_spoon", "portable", "sweet", "ready"],
    # Овощи
    "cucumber":        ["no_spoon", "portable", "crunchy", "ready", "budget"],
    "tomato":          ["no_spoon", "portable", "ready", "budget"],
    "carrot":          ["no_spoon", "portable", "crunchy", "ready", "budget"],
    "pepper_bell":     ["no_spoon", "crunchy", "ready"],
    "radish":          ["no_spoon", "crunchy", "ready", "budget"],
    "lettuce":         ["fresh", "ready"],
    "olives":          ["no_spoon", "salty", "ready"],
    # Хлеб и орехи
    "bread_wholegrain":["no_spoon", "ready", "budget"],
    "lavash":          ["no_spoon", "portable", "ready"],
    "almond":          ["no_spoon", "portable", "crunchy", "ready"],
    "cashew":          ["no_spoon", "portable", "crunchy", "ready"],
    "walnut":          ["no_spoon", "portable", "crunchy", "ready"],
    "peanut":          ["no_spoon", "portable", "crunchy", "ready", "budget"],
    "dark_chocolate":  ["no_spoon", "portable", "sweet", "ready"],
}

__all__ = ["STORE_PRODUCTS", "STORE_TAGS"]
