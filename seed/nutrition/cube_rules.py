"""Правила быстрого подбора: группы продуктов, порции и шаблоны.

Здесь данные, без логики. Логика — в services/cube.py.

Почему правило состава, а не список готовых комбинаций. Список из ста
десяти пар почти весь состоит из повторов с заменой: «творожное и фрукт»
встречается семь раз, «питьё и фрукт» — десять. Но перечислить все формы
списком тоже нельзя: сытные наборы из четырёх-пяти составляющих слишком
разнообразны, двадцать перечисленных форм покрыли только 72 из 110.

Поэтому здесь не перечень форм, а правило: в наборе обязателен белок,
к нему добавляются спутники, число составляющих задаёт режим голода.
Правило покрывает весь список и ещё тысячи наборов сверху, подстраивается
под остаток калорий и не требует переписывания, когда на полке появляется
новый продукт.

Сам список никуда не делся: он лежит в CURATED и служит проверкой. Если
правило не принимает то, что в нём есть, — сломано правило.
"""

from __future__ import annotations

# --- Группы: чем что заменяется --------------------------------------------
# Внутри группы продукты взаимозаменяемы. Именно отсюда берутся подсказки
# «нет индейки? — курица, тунец, два яйца».
GROUPS: dict[str, list[str]] = {
    "питьё": [
        "kefir", "ryazhenka", "ayran", "tan", "yogurt_drink",
        "yogurt_greek_drink", "protein_shake", "milk",
    ],
    "творожное": [
        "cottage_cheese", "greek_yogurt", "yogurt", "yogurt_high_protein",
        "protein_pudding",
    ],
    "сыр": [
        "cheese_hard", "cheese_sticks", "mozzarella", "mozzarella_mini",
        "cheese_adyghe", "feta",
    ],
    "мясо": [
        "egg", "chicken_smoked", "turkey_fillet", "pastrami", "ham",
        "tuna_canned", "salmon_salted", "surimi", "jerky",
    ],
    "растбелок": ["hummus", "tofu"],
    "батончик": ["protein_bar"],
    "фрукт": [
        "banana", "apple", "pear", "mandarin", "orange", "nectarine", "peach",
        "plum", "grapes", "berries", "kiwi", "fruit_puree", "persimmon",
    ],
    "овощ": [
        "cucumber", "tomato", "carrot", "pepper_bell", "radish", "celery",
        "veg_platter", "lettuce", "seaweed",
    ],
    "хруст": [
        "crispbread", "crispbread_rye", "crackers", "galette",
        "bread_wholegrain", "pita", "lavash", "bun_wholegrain",
    ],
    "сладкийхруст": ["granola", "cereal_bar"],
    "орехи": [
        "almond", "cashew", "walnut", "peanut", "pistachio", "pumpkin_seeds",
        "nut_mix", "dates", "olives", "dark_chocolate",
    ],
}

# Код продукта -> его группа.
GROUP_INDEX: dict[str, str] = {c: g for g, codes in GROUPS.items() for c in codes}

# Группы, которые считаются источником белка.
PROTEIN_GROUPS = frozenset({"питьё", "творожное", "сыр", "мясо", "растбелок", "батончик"})

# --- Порции ----------------------------------------------------------------
# Её ориентиры: орехи 20-30 г, сыр 30-60, творог 150-200, йогурт 150-250,
# кефир 200-330 мл, мясо 80-150, хлебцы 2-4 штуки, фрукт — одна штука.
# Берём середину: показываем всё равно диапазоном.
PORTIONS: dict[str, float] = {
    # питьё
    "kefir": 250, "ryazhenka": 250, "ayran": 300, "tan": 300, "milk": 250,
    "yogurt_drink": 290, "yogurt_greek_drink": 260, "protein_shake": 330,
    # творожное
    "cottage_cheese": 170, "greek_yogurt": 170, "yogurt": 170,
    "yogurt_high_protein": 170, "protein_pudding": 150,
    # сыр
    "cheese_hard": 40, "cheese_sticks": 60, "mozzarella": 60,
    "mozzarella_mini": 60, "cheese_adyghe": 70, "feta": 50,
    # мясо, рыба, яйца
    "egg": 100, "chicken_smoked": 100, "turkey_fillet": 110, "pastrami": 100,
    "ham": 80, "tuna_canned": 100, "salmon_salted": 60, "surimi": 100,
    "jerky": 50,
    # растительный белок и батончик
    "hummus": 60, "tofu": 100, "protein_bar": 60,
    # фрукты
    "banana": 120, "apple": 180, "pear": 170, "mandarin": 180, "orange": 180,
    "nectarine": 140, "peach": 150, "plum": 120, "grapes": 150, "berries": 125,
    "kiwi": 150, "fruit_puree": 90, "persimmon": 150,
    # овощи
    "cucumber": 150, "tomato": 150, "carrot": 150, "pepper_bell": 130,
    "radish": 120, "celery": 130, "veg_platter": 150, "lettuce": 80, "seaweed": 80,
    # хруст
    "crispbread": 30, "crispbread_rye": 30, "crackers": 25, "galette": 20,
    "bread_wholegrain": 60, "pita": 60, "lavash": 50, "bun_wholegrain": 70,
    "granola": 40, "cereal_bar": 40,
    # орехи и добавки
    "almond": 25, "cashew": 25, "walnut": 20, "peanut": 25, "pistachio": 25,
    "pumpkin_seeds": 25, "nut_mix": 25, "dates": 30, "olives": 40,
    "dark_chocolate": 20,
}

# --- Правило состава -------------------------------------------------------
# Режим голода: (подпись, ккал от, ккал до, составляющих от, до, можно ли
# два белка). Два источника белка — только когда человек всерьёз голоден:
# «кефир и творог» в лёгком перекусе выглядят как две еды подряд.
LEVELS: dict[str, tuple[str, int, int, int, int, bool]] = {
    "light":  ("🟢 Просто хочется что-нибудь пожевать", 100, 200, 1, 2, False),
    "normal": ("🟡 Я нормально голодна",                200, 350, 2, 3, False),
    "hungry": ("🔴 Я сейчас съем кассира",              350, 500, 3, 4, True),
    "meal":   ("🟣 Мне нужен почти нормальный приём",   400, 650, 3, 5, True),
}

# Сколько раз одна группа может войти в набор. Овощей и фруктов бывает два
# («огурец и черри»), всего остального — по одному.
MAX_PER_GROUP: dict[str, int] = {"овощ": 2, "фрукт": 2}
DEFAULT_MAX_PER_GROUP = 1

# Наборы без белка — только для самого лёгкого режима: «яблоко и орехи» это
# честный способ дотерпеть, но не еда.
LEVELS_WITHOUT_PROTEIN = frozenset({"light"})

# Чего хочется -> какие группы это закрывают. Пусто = закрывает что угодно.
CRAVING_GROUPS: dict[str, frozenset[str]] = {
    "sweet":   frozenset({"фрукт", "творожное", "сладкийхруст", "батончик"}),
    "salty":   frozenset({"мясо", "сыр", "растбелок", "овощ"}),
    "crunchy": frozenset({"хруст", "орехи", "овощ", "сладкийхруст"}),
    "drink":   frozenset({"питьё"}),
    "fresh":   frozenset({"овощ", "фрукт"}),
    "filling": frozenset(),
    "protein": frozenset({"мясо", "творожное", "растбелок", "батончик", "сыр"}),
    "comfort": frozenset({"творожное", "сладкийхруст", "сыр"}),
    "random":  frozenset(),
}

# Любимые формы: с них начинаем перебор, чтобы привычные сочетания
# выпадали чаще выдуманных. Это подсказка порядка, а не ограничение.
FAVOURITES: tuple[tuple[str, ...], ...] = (
    ("питьё", "фрукт"),
    ("творожное", "фрукт"),
    ("творожное", "фрукт", "орехи"),
    ("творожное", "сладкийхруст", "фрукт"),
    ("сыр", "фрукт"),
    ("сыр", "овощ", "хруст"),
    ("мясо", "овощ"),
    ("мясо", "овощ", "хруст"),
    ("мясо", "овощ", "хруст", "фрукт"),
    ("растбелок", "овощ", "хруст"),
    ("батончик", "фрукт"),
    ("питьё", "фрукт", "орехи"),
    ("фрукт", "орехи"),
    ("питьё",),
    ("творожное",),
)


# --- Что с чем едят --------------------------------------------------------
# Правило состава следит за формой набора, но форма — не еда. «Протеиновый
# батончик и сельдерей» проходит любую проверку по группам и при этом никто
# такого не ест. Поэтому к каждому источнику белка отдельно записано, что к
# нему вообще идёт.
PAIRING: dict[str, frozenset[str]] = {
    # Кисломолочное идёт почти ко всему: айран с индейкой и кефир с яйцом —
    # обычная еда, а не выдумка.
    "питьё":     frozenset({"фрукт", "орехи", "сладкийхруст", "хруст",
                            "мясо", "сыр", "творожное", "растбелок"}),
    "творожное": frozenset({"фрукт", "орехи", "сладкийхруст", "хруст", "питьё"}),
    "сыр":       frozenset({"фрукт", "овощ", "хруст", "орехи", "мясо",
                            "растбелок", "питьё"}),
    "мясо":      frozenset({"овощ", "хруст", "фрукт", "орехи", "сыр",
                            "питьё", "мясо"}),
    "растбелок": frozenset({"овощ", "хруст", "орехи", "сыр", "питьё", "фрукт"}),
    # Батончик самодостаточен: к нему разве что фрукт или что-то выпить.
    # Именно это правило отсекает «протеиновый батончик и сельдерей».
    "батончик":  frozenset({"фрукт", "питьё"}),
}

# Вкус продукта, если он не нейтральный. Солёное к сладкому белку и
# сладкое к солёному не ставим — кроме фрукта, который идёт ко всему.
SALTY_ONLY = frozenset({"olives", "seaweed", "celery", "radish", "crackers",
                        "pistachio", "pepper_bell"})
SWEET_ONLY = frozenset({"dark_chocolate", "dates", "granola", "cereal_bar",
                        "fruit_puree", "protein_bar"})
# Белок, к которому сладкое идёт естественно.
SWEET_PROTEINS = frozenset({"творожное", "батончик"})
SWEET_DRINKS = frozenset({"kefir", "ryazhenka", "milk", "yogurt_drink",
                          "yogurt_greek_drink", "protein_shake"})
# Солёное питьё — единственное, к чему сам по себе идёт овощ: айран с
# огурцом это еда, питьевой йогурт с листьями салата — нет.
SALTY_DRINKS = frozenset({"ayran", "tan"})
# Два фрукта в наборе уместны только к молочному: «йогурт, банан и ягоды».
TWO_FRUITS_WITH = frozenset({"питьё", "творожное"})

# К солёному белку идёт только целый фрукт: сыр с яблоком и моцарелла с
# нектарином — классика, а крабовое мясо с ягодами и хумус с фруктовым пюре
# — нет. К молочному подходит любой фрукт.
CALM_FRUITS = frozenset({"apple", "pear", "mandarin", "orange", "banana",
                         "nectarine", "peach", "plum", "persimmon"})

# Овощи на любителя: по одному на набор.
NICHE_VEG = frozenset({"seaweed", "celery", "radish"})


def _is_sweet_side(codes: list[str]) -> bool:
    """Сладкая ли у набора белковая сторона."""
    groups = {GROUP_INDEX[c] for c in codes if c in GROUP_INDEX}
    if groups & SWEET_PROTEINS:
        return True
    return any(c in SWEET_DRINKS for c in codes)


def pairing_ok(codes: list[str]) -> bool:
    """Едят ли такое вместе. Проверка здравого смысла, а не арифметики."""
    groups = [GROUP_INDEX[c] for c in codes if c in GROUP_INDEX]
    if len(groups) != len(codes):
        return False

    proteins = [g for g in groups if g in PROTEIN_GROUPS]
    others = [g for g in groups if g not in PROTEIN_GROUPS]

    # Каждый спутник должен подходить хотя бы одному источнику белка.
    salty_drink = any(c in SALTY_DRINKS for c in codes)
    for companion in others:
        if not proteins:
            continue
        if any(companion in PAIRING[p] for p in proteins):
            continue
        if companion == "овощ" and salty_drink:
            continue
        return False
    # Два белка тоже должны сочетаться между собой.
    for first in proteins:
        for second in proteins:
            if first != second and second not in PAIRING[first]:
                return False

    sweet_side = _is_sweet_side(codes)
    for code in codes:
        if code in SALTY_ONLY and sweet_side:
            return False
        if code in SWEET_ONLY and proteins and not sweet_side:
            return False

    if groups.count("фрукт") > 1 and not (set(proteins) & TWO_FRUITS_WITH):
        return False

    # Сельдерей с морской капустой в одном наборе — витрина здоровья, а не
    # то, что человек купит и съест. Редкий овощ пусть будет один.
    if sum(1 for c in codes if c in NICHE_VEG) > 1:
        return False

    if proteins and not sweet_side:
        fruits = [c for c in codes if GROUP_INDEX.get(c) == "фрукт"]
        if any(c not in CALM_FRUITS for c in fruits):
            return False
    return True


def slots_ok(groups, level: str) -> bool:
    """Годится ли такой состав для этого режима голода.

    `groups` — список названий групп в наборе.
    """
    settings = LEVELS.get(level)
    if settings is None:
        return False
    _, _, _, min_items, max_items, two_proteins = settings

    if not min_items <= len(groups) <= max_items:
        return False

    counts: dict[str, int] = {}
    for name in groups:
        counts[name] = counts.get(name, 0) + 1
        # Белковые группы считаются общим числом белков ниже: два яйца с
        # крабовым мясом — это два белка, а не нарушение лимита группы.
        if name in PROTEIN_GROUPS:
            continue
        if counts[name] > MAX_PER_GROUP.get(name, DEFAULT_MAX_PER_GROUP):
            return False

    proteins = sum(n for name, n in counts.items() if name in PROTEIN_GROUPS)
    if proteins == 0:
        return level in LEVELS_WITHOUT_PROTEIN
    if proteins > 2:
        return False
    return proteins < 2 or two_proteins


# --- Проверочный список ----------------------------------------------------
# Те самые K001-K110. Хранятся кодами продуктов: если какой-то из них исчез
# из справочника или правила разучились собирать такую пару — тест упадёт.
CURATED: list[tuple[str, tuple[str, ...]]] = [
    # LIGHT
    ("K001", ("greek_yogurt", "apple")),
    ("K002", ("kefir", "apple")),
    ("K003", ("kefir", "mandarin")),
    ("K004", ("ryazhenka", "apple")),
    ("K005", ("protein_pudding",)),
    ("K006", ("yogurt_high_protein",)),
    ("K007", ("cottage_cheese", "berries")),
    ("K008", ("cottage_cheese", "banana")),
    ("K009", ("cheese_hard", "apple")),
    ("K010", ("cheese_sticks", "pear")),
    ("K011", ("mozzarella_mini", "tomato")),
    ("K012", ("egg", "cucumber")),
    ("K013", ("egg", "cucumber")),
    ("K014", ("hummus", "carrot")),
    ("K015", ("hummus", "cucumber")),
    ("K016", ("ayran", "apple")),
    ("K017", ("tan", "cucumber")),
    ("K018", ("protein_shake",)),
    ("K019", ("banana", "almond")),
    ("K020", ("apple", "peanut")),
    ("K021", ("pear", "cheese_hard")),
    ("K022", ("tofu", "tomato")),
    ("K023", ("surimi", "cucumber")),
    ("K024", ("carrot", "mozzarella_mini")),
    ("K025", ("berries", "yogurt")),
    # NORMAL
    ("K026", ("cottage_cheese", "banana")),
    ("K027", ("cottage_cheese", "apple")),
    ("K028", ("cottage_cheese", "pear")),
    ("K029", ("greek_yogurt", "banana", "walnut")),
    ("K030", ("greek_yogurt", "apple", "almond")),
    ("K031", ("yogurt_high_protein", "banana")),
    ("K032", ("protein_pudding", "banana")),
    ("K033", ("protein_pudding", "berries")),
    ("K034", ("protein_shake", "apple")),
    ("K035", ("protein_shake", "banana")),
    ("K036", ("kefir", "banana", "walnut")),
    ("K037", ("ryazhenka", "banana")),
    ("K038", ("mozzarella", "tomato", "crispbread")),
    ("K039", ("cheese_adyghe", "cucumber", "crispbread")),
    ("K040", ("egg", "cucumber", "crispbread")),
    ("K041", ("egg", "apple", "crispbread")),
    ("K042", ("chicken_smoked", "cucumber", "crispbread")),
    ("K043", ("turkey_fillet", "tomato", "crispbread")),
    ("K044", ("chicken_smoked", "cucumber")),
    ("K045", ("tuna_canned", "cucumber", "crispbread")),
    ("K046", ("tuna_canned", "tomato", "crispbread")),
    ("K047", ("hummus", "carrot", "crispbread")),
    ("K048", ("hummus", "cucumber", "crispbread")),
    ("K049", ("hummus", "pepper_bell", "crispbread")),
    ("K050", ("tofu", "veg_platter", "crispbread")),
    ("K051", ("cheese_hard", "apple", "crispbread")),
    ("K052", ("mozzarella", "nectarine", "crispbread")),
    ("K053", ("yogurt", "granola", "berries")),
    ("K054", ("greek_yogurt", "fruit_puree")),
    ("K055", ("kefir", "cereal_bar")),
    ("K056", ("ayran", "crispbread", "cheese_hard")),
    ("K057", ("tan", "crispbread", "turkey_fillet")),
    ("K058", ("surimi", "cucumber", "crispbread")),
    ("K059", ("mozzarella_mini", "apple", "crispbread")),
    ("K060", ("egg", "tomato", "crispbread")),
    # HUNGRY
    ("K061", ("cottage_cheese", "banana", "walnut")),
    ("K062", ("cottage_cheese", "apple", "crispbread", "walnut")),
    ("K063", ("greek_yogurt", "banana", "granola")),
    ("K064", ("yogurt_high_protein", "banana", "almond")),
    ("K065", ("protein_shake", "banana", "almond")),
    ("K066", ("kefir", "banana", "cheese_hard", "crispbread")),
    ("K067", ("chicken_smoked", "crispbread", "veg_platter")),
    ("K068", ("turkey_fillet", "crispbread", "tomato", "apple")),
    ("K069", ("chicken_smoked", "cheese_hard", "crispbread", "cucumber")),
    ("K070", ("tuna_canned", "crispbread", "cucumber", "apple")),
    ("K071", ("tuna_canned", "lettuce", "bread_wholegrain", "apple")),
    ("K072", ("salmon_salted", "crispbread", "cucumber")),
    ("K073", ("egg", "cheese_hard", "crispbread", "cucumber")),
    ("K074", ("mozzarella", "crispbread", "tomato", "apple")),
    ("K075", ("cheese_adyghe", "lavash", "cucumber", "tomato")),
    ("K076", ("hummus", "crispbread", "veg_platter", "apple")),
    ("K077", ("hummus", "pita", "carrot", "cucumber")),
    ("K078", ("tofu", "crispbread", "veg_platter", "apple")),
    ("K079", ("protein_pudding", "banana", "walnut")),
    ("K080", ("yogurt", "granola", "banana")),
    ("K081", ("kefir", "banana", "crispbread", "peanut")),
    ("K082", ("ryazhenka", "banana", "walnut")),
    ("K083", ("ayran", "turkey_fillet", "crispbread", "cucumber")),
    ("K084", ("tan", "egg", "crispbread", "tomato")),
    ("K085", ("cheese_hard", "crispbread", "apple", "walnut")),
    ("K086", ("surimi", "crispbread", "cucumber", "apple")),
    ("K087", ("chicken_smoked", "lettuce", "bread_wholegrain")),
    ("K088", ("turkey_fillet", "pita", "veg_platter")),
    ("K089", ("tuna_canned", "pita", "veg_platter")),
    ("K090", ("mozzarella", "pita", "veg_platter", "apple")),
    # MEAL
    ("K091", ("chicken_smoked", "lavash", "veg_platter", "ayran")),
    ("K092", ("turkey_fillet", "pita", "tomato", "lettuce")),
    ("K093", ("tuna_canned", "bread_wholegrain", "veg_platter", "apple")),
    ("K094", ("egg", "bread_wholegrain", "veg_platter", "kefir")),
    ("K095", ("hummus", "pita", "veg_platter", "ayran")),
    ("K096", ("tofu", "crispbread", "lettuce", "apple", "walnut")),
    ("K097", ("mozzarella", "bread_wholegrain", "tomato", "cucumber", "apple")),
    ("K098", ("cheese_adyghe", "lavash", "veg_platter", "ayran")),
    ("K099", ("chicken_smoked", "crispbread", "tomato", "apple", "cheese_hard")),
    ("K100", ("turkey_fillet", "crispbread", "cucumber", "banana", "kefir")),
    ("K101", ("tuna_canned", "crispbread", "tomato", "apple", "olives")),
    ("K102", ("salmon_salted", "bread_wholegrain", "cucumber", "lettuce")),
    ("K103", ("protein_shake", "banana", "crispbread", "almond")),
    ("K104", ("cottage_cheese", "banana", "granola", "berries")),
    ("K105", ("greek_yogurt", "granola", "banana", "walnut")),
    ("K106", ("kefir", "cottage_cheese", "apple")),
    ("K107", ("hummus", "crispbread", "pepper_bell", "carrot", "cheese_hard")),
    ("K108", ("surimi", "egg", "crispbread", "veg_platter")),
    ("K109", ("mozzarella", "crispbread", "veg_platter", "walnut")),
    ("K110", ("tofu", "pita", "veg_platter", "olives")),
]

__all__ = ["CRAVING_GROUPS", "CURATED", "FAVOURITES", "GROUPS", "GROUP_INDEX",
           "LEVELS", "MAX_PER_GROUP", "PAIRING", "PORTIONS", "PROTEIN_GROUPS",
           "pairing_ok", "slots_ok"]
