"""Меню-конструктор Анастасии на 4 дня («Обезжириватель»).

Особенность этого файла в том, что в источнике блюда описаны сборкой, а не
рецептом: «салат — фрикадельки, цветная капуста, маринованные грибочки,
хлеб, зелень, соус». Что положить — сказано, сколько — нет.

Поэтому граммы здесь подобраны по её же обычным размерам порций: медиана по
64 её рецептам для каждого продукта (курица 150 г, крупа сухая 55–70 г,
йогурт в соусе 30 г, орехи 20 г, зелень 15 г, хлеб 30 г). Где она всё-таки
дала количества — в закупке на суп: фасоль, сыр и картофель, — взяты они.

Каждое такое блюдо помечено estimated=True, и приложение честно пишет об
этом в карточке рецепта. Выдавать подобранные порции за авторские нельзя.
"""

from __future__ import annotations

from utils.measures import HANDFUL_G, spoon, teaspoon

B, L, D, S = "breakfast", "lunch", "dinner", "snack"

FOURDAY_DISHES: list[dict] = []

SRC = "Меню-конструктор Анастасии на 4 дня"
NOTE = ("Порции подобраны по обычным размерам её рецептов — в самом меню "
        "на 4 дня граммы не указаны.")

# Её медианы по 64 рецептам, чтобы не подбирать числа на глаз.
CHICKEN, FISH, MINCE = 150.0, 150.0, 100.0
GRAIN, PASTA, OATS = 55.0, 70.0, 45.0
CURD, YOGURT, NUTS = 125.0, 30.0, 20.0
CAULI, CARROT, TOMATO, PEAS, BEANS = 120.0, 80.0, 100.0, 40.0, 100.0
MUSHROOMS, BREAD, CHEESE = 80.0, 30.0, 30.0
# В этих сборках зелень — основа салата, а не посыпка: у неё в таких блюдах
# руккола и шпинат доходят до 30 г.
GREENS = 30.0


def _dish(code, name, meals, components, *, instructions, portions=1, minutes=15,
          preps=(), day=""):
    FOURDAY_DISHES.append(dict(
        code=code, name=name, meal_types=";".join(meals), portions=portions,
        instructions=instructions, notes=NOTE, minutes=minutes,
        author=True, source=f"{SRC}, {day}" if day else SRC,
        prep_codes=";".join(preps), estimated=True, components=components,
    ))


def c(product, grams, raw="", optional=False, countable=False):
    return dict(product_code=product, grams=float(grams), raw_amount=raw,
                optional=optional, countable=countable)


# --- Завтраки -------------------------------------------------------------

_dish("f_curd_bowl", "Творожный боул с хурмой и грецкими орехами", [B], [
    c("cottage_cheese", CURD, "творог"), c("yogurt", YOGURT, "йогурт"),
    c("persimmon", 150, "1 хурма", countable=True), c("walnut", NUTS, "грецкие орехи"),
], instructions=(
    "Творог смешать с йогуртом до кремовой текстуры. Сверху выложить нарезанную хурму "
    "и рубленые орехи."
), minutes=5, day="дни 1 и 3")

_dish("f_oats_carrot", "Овсянка с морковью, йогуртом и грецким орехом", [B], [
    c("oats", OATS, "овсянка"), c("water", 150, "вода"), c("carrot", 50, "морковь"),
    c("yogurt", YOGURT, "йогурт"), c("walnut", NUTS, "грецкие орехи"),
    c("spices", 0, "корица по желанию"),
], instructions=(
    "Овсянку сварить на воде в пропорции 1:2,5. Морковь натереть и добавить в конце "
    "варки. Подавать с ложкой йогурта и орехами."
), minutes=15, day="день 2")

_dish("f_oats_persimmon", "Овсянка с хурмой, йогуртом и грецким орехом", [B], [
    c("oats", OATS, "овсянка"), c("water", 150, "вода"),
    c("persimmon", 150, "1 хурма", countable=True), c("yogurt", YOGURT, "йогурт"),
    c("walnut", NUTS, "грецкие орехи"),
], instructions=(
    "Овсянку сварить на воде. Сверху выложить нарезанную хурму, ложку йогурта и орехи."
), minutes=15, day="день 4")

# --- Обеды и ужины --------------------------------------------------------

# Единственное место, где она дала количества: фасоль, сыр и картофель
# указаны в закупке именно на суп. Их и берём, остальное — по медианам.
# Кастрюля делится на три тарелки: у неё суп идёт в обед первого дня и
# «остаток» во второй, а порция в 700 г — это нормальная тарелка супа.
_dish("f_meatball_soup", "Суп с фрикадельками, цветной капустой и фасолью", [L, D], [
    c("mince_mixed", 300, "фрикадельки"), c("breadcrumbs", 34, "в фрикадельках"),
    c("cauliflower", 300, "цветная капуста"), c("beans_white", 240, "1 банка"),
    c("potato", 450, "400–500 г"), c("cheese_hard", 60, "чеддер 60 г"),
    c("water", 1200, "бульон"), c("herbs", 20, "зелень"), c("salt", 0, "соль"),
], instructions=(
    "В кипящую воду добавить картофель, затем цветную капусту и фасоль. Выложить "
    "готовые фрикадельки, добавить тёртый сыр и соль. Прогреть 5–7 минут."
), portions=3, minutes=20, day="дни 1 и 2",
   preps=("meatballs_baked", "cauliflower_yogurt"))

_dish("f_meatball_salad", "Салат с фрикадельками, цветной капустой и грибами", [D], [
    c("mince_mixed", MINCE, "фрикадельки"), c("breadcrumbs", 11, "в фрикадельках"),
    c("cauliflower", CAULI, "цветная капуста"), c("mushrooms", MUSHROOMS, "маринованные грибы"),
    c("bread_wholegrain", BREAD, "1 ломтик"), c("arugula", GREENS, "руккола или шпинат"),
    c("yogurt", YOGURT, "соус"), c("olive_oil", teaspoon("масло"), "соус"),
    c("salt", 0, "соль и перец"),
], instructions=(
    "Собрать салат из готовых фрикаделек, цветной капусты и маринованных грибов. "
    "Добавить зелень и хлеб. Соус — йогурт, масло, соль и перец — добавить при подаче, "
    "а не заранее."
), minutes=10, day="день 1",
   preps=("meatballs_baked", "cauliflower_yogurt", "mushrooms_marinated"))

_dish("f_chicken_bowl", "Боул с курицей, булгуром и морковью", [L, D], [
    c("chicken_fillet", CHICKEN, "запечённое филе"), c("bulgur", GRAIN, "булгур сухой"),
    c("carrot", CARROT, "морковь со шрирачей"), c("sriracha", 2.4, "в моркови"),
    c("cauliflower", CAULI, "цветная капуста"), c("tomato", TOMATO, "помидоры черри"),
    c("arugula", GREENS, "руккола или шпинат"), c("yogurt", YOGURT, "соус"),
    c("mustard", teaspoon("горчица"), "соус"), c("lemon", teaspoon("сок"), "соус"),
    c("honey", teaspoon("мёд"), "соус"),
], instructions=(
    "Булгур отварить в пропорции 1:2 двенадцать–пятнадцать минут. Выложить секторами "
    "булгур, курицу, морковь, цветную капусту, черри и зелень. Соус — йогурт, горчица, "
    "лимонный сок и мёд — добавить при подаче."
), minutes=15, day="день 2",
   preps=("chicken_baked_plain", "carrot_sriracha", "cauliflower_yogurt"))

_dish("f_pasta_salmon", "Макароны с горбушей, горошком и морковью", [L, D], [
    c("pasta", PASTA, "макароны сухие"), c("salmon_pink", FISH, "запечённая горбуша"),
    c("green_peas", PEAS, "зелёный горошек"), c("carrot", CARROT, "морковь"),
    c("herbs", GREENS, "зелень"), c("olive_oil", teaspoon("масло"), "масло"),
    c("lemon", teaspoon("сок"), "лимон"),
], instructions=(
    "Макароны отварить до состояния al dente. Горошек прогреть. Смешать с готовой "
    "горбушей и морковью, сбрызнуть маслом и лимоном, посыпать зеленью."
), minutes=15, day="дни 3 и 4",
   preps=("salmon_baked", "carrot_sriracha"))

_dish("f_chicken_mushroom_salad", "Салат с курицей и маринованными грибами", [D], [
    c("chicken_fillet", CHICKEN, "запечённое филе"),
    c("mushrooms", MUSHROOMS, "маринованные грибы"),
    c("bread_wholegrain", BREAD, "1 ломтик"), c("arugula", GREENS, "руккола или шпинат"),
    c("yogurt", YOGURT, "соус"), c("olive_oil", teaspoon("масло"), "соус"),
    c("salt", 0, "соль"),
], instructions=(
    "Собрать салат из готовой курицы, маринованных грибов и зелени, добавить хлеб. "
    "Заправить йогуртом с маслом и солью перед подачей."
), minutes=10, day="день 3",
   preps=("chicken_baked_plain", "mushrooms_marinated"))

_dish("f_meatball_bowl", "Боул с фрикадельками, булгуром и грибами", [L, D], [
    c("mince_mixed", MINCE, "фрикадельки"), c("breadcrumbs", 11, "в фрикадельках"),
    c("bulgur", GRAIN, "булгур сухой"), c("cauliflower", CAULI, "цветная капуста"),
    c("green_peas", PEAS, "зелёный горошек"),
    c("mushrooms", MUSHROOMS, "маринованные грибы"),
    c("arugula", GREENS, "руккола или шпинат"), c("yogurt", YOGURT, "ореховый соус"),
    c("nut_butter", 15, "ореховый соус"),
    c("soy_sauce", spoon("соевый соус") * 0.6, "ореховый соус"),
    c("lemon", teaspoon("сок"), "ореховый соус"), c("water", 10, "ореховый соус"),
], instructions=(
    "Булгур отварить. Выложить секторами булгур, фрикадельки, цветную капусту, горошек, "
    "грибы и зелень. Для орехового соуса смешать йогурт, ореховую пасту, соевый соус, "
    "лимонный сок и воду до нужной густоты."
), minutes=15, day="день 4",
   preps=("meatballs_baked", "cauliflower_yogurt", "mushrooms_marinated"))

__all__ = ["FOURDAY_DISHES"]
