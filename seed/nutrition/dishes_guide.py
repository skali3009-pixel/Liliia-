"""Блюда из гайда «Готовим один раз — собираем всю неделю».

Семь дней, завтрак/обед/ужин плюс смузи. Отличие от рецептов по дням в том,
что здесь блюда собираются из заготовок: «берём готовую индейку», «берём
шакшуку-основу». Поэтому у них указаны prep_codes — приложение показывает,
что из этого уже стоит в холодильнике, и время сборки, а не полной готовки.

Где в гайде вес дан для готовой крупы («150 г готовой гречки»), в состав
записан сухой вес: справочник считает КБЖУ по сухому продукту. Пропорция
взята обычная для варки — примерно 1 к 2,5.
"""

from __future__ import annotations

from utils.measures import CLOVE_G, HANDFUL_G, SLICE_BREAD_G, spoon, teaspoon

B, L, D, S = "breakfast", "lunch", "dinner", "snack"

GUIDE_DISHES: list[dict] = []


def _dish(code, name, meals, components, *, instructions, source, portions=1,
          minutes=20, notes="", preps=()):
    GUIDE_DISHES.append(dict(
        code=code, name=name, meal_types=";".join(meals), portions=portions,
        instructions=instructions, notes=notes, minutes=minutes,
        author=True, source=source, prep_codes=";".join(preps), components=components,
    ))


def c(product, grams, raw="", optional=False, countable=False):
    return dict(product_code=product, grams=float(grams), raw_amount=raw,
                optional=optional, countable=countable)


SRC = "Гайд Анастасии «Готовим один раз»"

_dish("g_frittata", "Фриттата с овощами и сыром", [B], [
    c("egg", 100, "2 шт.", countable=True), c("milk", 30, "30 мл"),
    c("pepper_bell", 50, "50 г"), c("tomato", 60, "60 г"),
    c("spinach", 30, "30 г"), c("cheese_hard", 30, "30 г"),
    c("olive_oil", teaspoon("масло") / 2, "½ ч. л."),
], instructions=(
    "Овощи слегка прогреть. Яйца взбить с молоком, смешать с овощами, посыпать сыром. "
    "Запекать 15–18 минут при 180 °C."
), source=f"{SRC}, понедельник", minutes=20)

_dish("g_turkey_potato", "Индейка с картофелем и салатом", [L, D], [
    c("turkey_fillet", 180, "готовая индейка"), c("yogurt", 45, "маринад и заправка"),
    c("potato", 250, "250 г"), c("cabbage", 120, "120 г"), c("cucumber", 100, "100 г"),
    c("herbs", HANDFUL_G, "зелень"), c("mustard", teaspoon("горчица"), "горчица"),
    c("honey", teaspoon("мёд"), "мёд"), c("lemon", teaspoon("сок"), "лимон"),
], instructions=(
    "Берём готовую индейку. Картофель запечь дольками при 200 °C 30–35 минут. Салат "
    "нарезать и заправить перед подачей."
), source=f"{SRC}, понедельник", minutes=35, preps=("turkey_marinated",),
   notes="Индейка готовится заранее — в день подачи остаётся картофель и салат.")

_dish("g_shakshuka", "Шакшука с хлебом", [B], [
    c("onion", 50, "из основы"), c("tomato_canned", 112, "из основы"),
    c("garlic", 2, "из основы"), c("olive_oil", 4, "из основы"),
    c("egg", 100, "2 шт.", countable=True),
    c("bread_wholegrain", 40, "40 г"), c("spices", 0, "паприка, зира"),
], instructions=(
    "Разогреть шакшуку-основу, сделать углубления, добавить яйца. Готовить под крышкой "
    "4–6 минут. Подать с хлебом."
), source=f"{SRC}, вторник", minutes=10, preps=("shakshuka_base",))

_dish("g_puttanesca_plate", "Курица путанеска с гречкой и цветной капустой", [L, D], [
    c("chicken_fillet", 225, "из заготовки"), c("tomato_canned", 100, "из заготовки"),
    c("olives", 20, "из заготовки"), c("olive_oil", 8, "из заготовок"),
    c("buckwheat", 70, "70 г сухой"), c("cauliflower", 220, "из заготовки"),
    c("garlic", CLOVE_G, "из заготовок"), c("spices", 0, "орегано, паприка"),
], instructions="Берём три готовые базы: путанеска, гречка, цветная капуста. Разогреть и собрать тарелку.",
   source=f"{SRC}, вторник и среда", minutes=10,
   preps=("chicken_puttanesca", "buckwheat_cooked", "cauliflower_baked"),
   notes="Полностью из заготовок — в день подачи только разогреть.")

_dish("g_cordon_salad", "Кордон блю с салатом", [D], [
    c("chicken_fillet", 150, "из заготовки"), c("cheese_hard", 40, "из заготовки"),
    c("ham", 40, "из заготовки"), c("cabbage", 120, "120 г"),
    c("cucumber", 100, "100 г"), c("yogurt", 30, "йогурт"),
    c("lemon", teaspoon("сок"), "лимон"),
], instructions="Разогреть кордон блю, салат собрать свежим. При желании добавить хлеб или крупу.",
   source=f"{SRC}, вторник и среда", minutes=10, preps=("cordon_bleu",))

_dish("g_buckwheat_egg", "Гречка с томатной основой, яйцом и сыром", [B], [
    c("buckwheat", 55, "150 г готовой"), c("onion", 50, "из основы"),
    c("tomato_canned", 112, "из основы"), c("olive_oil", 4, "из основы"),
    c("cheese_hard", 20, "20 г"), c("egg", 75, "1–2 шт.", countable=True),
], instructions=(
    "Разогреть гречку и основу. Добавить сыр, сверху — жареное яйцо или пашот."
), source=f"{SRC}, среда", minutes=10,
   preps=("buckwheat_cooked", "shakshuka_base"))

_dish("g_rice_casserole", "Рисовая запеканка с сыром и овощами", [B], [
    c("rice", 55, "150 г готового"), c("egg", 100, "2 шт.", countable=True),
    c("cauliflower", 80, "80 г"), c("green_peas", 30, "горошек"),
    c("cheese_hard", 30, "30 г"), c("salt", 0, "соль"),
], instructions="Смешать и запечь 20 минут при 180 °C. Можно собрать с вечера.",
   source=f"{SRC}, четверг", minutes=25, preps=("rice_cooked", "cauliflower_baked"))

_dish("g_mackerel_pasta", "Запечённая скумбрия с макаронами и салатом", [L], [
    c("mackerel_canned", 150, "150 г"), c("pasta", 70, "70 г сухих"),
    c("cabbage", 100, "100 г"), c("cucumber", 50, "50 г"), c("radish", 40, "40 г"),
    c("green_peas", 30, "30 г"), c("yogurt", 30, "йогурт"),
    c("mustard", teaspoon("горчица"), "горчица"), c("lemon", teaspoon("сок"), "лимон"),
], instructions=(
    "Скумбрию запекать 20 минут при 190 °C с лимоном. Макароны отварить 8–10 минут. "
    "Салат собрать свежим."
), source=f"{SRC}, четверг", minutes=30)

_dish("g_mackerel_salad", "Салат со скумбрией", [D], [
    c("mackerel_canned", 150, "готовая скумбрия"), c("cabbage", 100, "100 г"),
    c("cucumber", 50, "50 г"), c("radish", 40, "40 г"), c("green_peas", 30, "30 г"),
    c("herbs", HANDFUL_G, "зелень"), c("lemon", teaspoon("сок"), "лимон"),
    c("olive_oil", teaspoon("масло"), "масло"),
], instructions="Разобрать скумбрию и смешать с овощами. Заправить лимоном и маслом.",
   source=f"{SRC}, четверг", minutes=10)

_dish("g_pate_sandwich", "Бутерброд с паштетом из скумбрии и яйцом", [B], [
    c("egg", 100, "2 шт.", countable=True), c("bread_wholegrain", 40, "40 г"),
    c("mackerel_canned", 27, "из паштета"), c("yogurt", 10, "из паштета"),
    c("mustard", 1, "из паштета"),
], instructions="Намазать паштет на хлеб, приготовить яйцо и собрать бутерброд.",
   source=f"{SRC}, пятница", minutes=10, preps=("mackerel_pate",))

_dish("g_pumpkin_soup_chicken", "Тыквенный суп-пюре с курицей и хлебом", [L], [
    c("pumpkin", 180, "из супа"), c("onion", 18, "из супа"),
    c("cream10", 27, "из супа"), c("water", 200, "из супа"),
    c("chicken_fillet", 120, "готовая курица"),
    c("bread_wholegrain", SLICE_BREAD_G, "хлеб по желанию", optional=True),
    c("spices", 0, "мускат, соль"),
], instructions="Разогреть суп и курицу, подать вместе.",
   source=f"{SRC}, пятница и суббота", minutes=10,
   preps=("pumpkin_soup", "chicken_baked_plain"))

_dish("g_chicken_salad", "Салат с курицей", [D], [
    c("chicken_fillet", 150, "готовое филе"), c("cabbage", 100, "100 г"),
    c("carrot", 50, "50 г"), c("herbs", HANDFUL_G, "зелень"),
    c("yogurt", 30, "йогурт"), c("lemon", teaspoon("сок"), "лимон"),
    c("mustard", teaspoon("горчица"), "горчица"),
], instructions="Овощи смешать или выложить секторами. Добавить курицу и соус.",
   source=f"{SRC}, пятница", minutes=10, preps=("chicken_baked_plain",))

_dish("g_buckwheat_bowl", "Боул с гречкой, яйцом и овощами", [B], [
    c("buckwheat", 60, "150 г готовой"), c("egg", 100, "2 шт.", countable=True),
    c("cabbage_red", 80, "80 г"), c("carrot", 50, "морковь"),
    c("herbs", HANDFUL_G, "зелень"), c("soy_sauce", spoon("соевый соус") * 0.7, "соевый соус"),
    c("olive_oil", teaspoon("масло"), "масло"), c("honey", teaspoon("мёд"), "мёд"),
    c("lemon", teaspoon("сок"), "лимон"),
], instructions="Выложить гречку, яйца и овощи секторами, заправить соусом.",
   source=f"{SRC}, суббота", minutes=10, preps=("buckwheat_cooked",))

_dish("g_fish_rice", "Белая рыба с рисом, овощами и зелёным соусом", [L, D], [
    c("fish_white", 175, "150–200 г"), c("rice", 65, "150–180 г готового"),
    c("tomato", 100, "овощи"), c("cucumber", 100, "овощи"),
    c("yogurt", 40, "зелёный соус"), c("herbs", 6, "зелёный соус"),
    c("lemon", 3, "зелёный соус"), c("olive_oil", teaspoon("масло"), "масло"),
], instructions=(
    "Рыбу запечь 15–20 минут при 190–200 °C. Рис разогреть, овощи нарезать, добавить соус."
), source=f"{SRC}, суббота и воскресенье", minutes=25,
   preps=("rice_cooked", "green_sauce"))

_dish("g_fish_bowl", "Боул с рыбой, рисом и овощами", [D], [
    c("fish_white", 175, "готовая рыба"), c("rice", 65, "готовый рис"),
    c("tomato", 100, "овощи"), c("cucumber", 100, "овощи"),
    c("yogurt", 40, "зелёный соус"), c("herbs", 6, "зелёный соус"),
    c("lemon", 3, "зелёный соус"), c("olive_oil", teaspoon("масло"), "масло"),
], instructions=(
    "Рыбу разобрать на крупные кусочки. Рис и овощи выложить секторами, добавить рыбу "
    "и соус. Это новая сборка из тех же баз."
), source=f"{SRC}, воскресенье", minutes=10,
   preps=("rice_cooked", "green_sauce"),
   notes="Та же база, что и в обед, но собрана иначе — чтобы не повторять блюдо буквально.")

_dish("g_croque_madame", "Крок-мадам с паштетом из скумбрии", [B], [
    c("bread_wholegrain", SLICE_BREAD_G * 2, "2 ломтика"),
    c("mackerel_canned", 34, "из паштета"), c("yogurt", 12, "из паштета"),
    c("cheese_hard", 35, "30–40 г"), c("egg", 50, "1 шт.", countable=True),
    c("olive_oil", teaspoon("масло"), "1 ч. л."),
], instructions=(
    "Хлеб намазать паштетом, добавить сыр, накрыть вторым ломтиком. Обжарить по 2–3 "
    "минуты с каждой стороны. Сверху — яйцо-глазунья."
), source=f"{SRC}, воскресенье", minutes=15, preps=("mackerel_pate",))

# --- Смузи гайда: кефир 250 мл + два компонента + специя -------------------
_GUIDE_SMOOTHIES = [
    ("g_smoothie_mon", "Смузи хурма — банан", [("persimmon", 90), ("banana", 85)],
     "корица", "понедельник"),
    ("g_smoothie_tue", "Смузи морковь — яблоко", [("carrot", 90), ("apple", 85)],
     "имбирь", "вторник"),
    ("g_smoothie_wed", "Смузи свёкла — банан с какао", [("beetroot", 90), ("banana", 85)],
     "какао", "среда"),
    ("g_smoothie_thu", "Смузи цветная капуста — яблоко",
     [("cauliflower", 90), ("apple", 85)], "кардамон", "четверг"),
    ("g_smoothie_fri", "Смузи морковь — хурма", [("carrot", 90), ("persimmon", 85)],
     "имбирь", "пятница"),
    ("g_smoothie_sat", "Смузи свёкла — яблоко с корицей",
     [("beetroot", 90), ("apple", 85)], "корица", "суббота"),
    ("g_smoothie_sun", "Смузи морковь — яблоко с цедрой",
     [("carrot", 90), ("apple", 85)], "цедра апельсина, соль", "воскресенье"),
]

for code, name, parts, spice, day in _GUIDE_SMOOTHIES:
    components = [c("kefir", 250, "250 мл")]
    components += [c(product, grams, f"{grams} г") for product, grams in parts]
    if spice == "какао":
        components.append(c("cocoa", 3, "какао"))
    else:
        components.append(c("spices", 0, spice))
    _dish(code, name, [S], components,
          instructions="Всё взбить в блендере до однородности.",
          source=f"{SRC}, {day}", minutes=5,
          notes="Овощи и фрукты можно нарезать кубиками и заморозить впрок.")

__all__ = ["GUIDE_DISHES"]
