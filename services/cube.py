"""Кубик: что съесть прямо сейчас, если готовить негде.

Человек в магазине не знает, сколько у него осталось калорий. Он знает,
насколько голоден и чего хочется. Поэтому спрашиваем именно это, а
остаток — если он есть — подставляем сами.

Как собирается набор. Сначала белок: без него это не еда, а сахар с
перерывом. Потом спутники — фрукт, овощ, хруст, орехи — пока не наберётся
нужная сытость. Состав проверяется правилом из cube_rules, порции
подгоняются под режим. КБЖУ считает арифметика по нашей же таблице
продуктов; показываем его диапазоном, потому что у каждой марки йогурта
он свой, и точность до килокалории была бы враньём.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from models import Product
from seed.nutrition.cube_rules import (
    CRAVING_GROUPS,
    FAVOURITES,
    GROUPS,
    LEVELS,
    PORTIONS,
    PROTEIN_GROUPS,
    pairing_ok,
    slots_ok,
)

# Группа каждого продукта: строится один раз.
GROUP_OF: dict[str, str] = {code: name for name, codes in GROUPS.items() for code in codes}

# Порции можно ужать или растянуть, но не переврать: половина банана — это
# половина банана, а четверть банана — это уже не то, что человек купит.
MIN_SCALE, MAX_SCALE = 0.6, 1.4

# Сколько последних наборов помним, чтобы не предлагать одно и то же.
REMEMBER = 10

# Ниже этой доли белка «почти нормальный приём пищи» не считается едой.
# Правило Анастасии; на перекусы она его не распространяет, и мы тоже.
MIN_PROTEIN_SHARE = 0.15


PIECE_WORDS = {0.5: "½ шт.", 1.0: "1 шт.", 1.5: "1½ шт.", 2.0: "2 шт.",
               2.5: "2½ шт.", 3.0: "3 шт."}

# Что считают поштучно, кроме фруктов.
COUNTED = frozenset({"egg", "protein_bar", "cereal_bar", "jerky",
                     "bun_wholegrain", "pita"})


@dataclass(frozen=True)
class Item:
    """Одна составляющая набора."""

    code: str
    name: str
    grams: float
    group: str
    piece_g: float | None = None

    @property
    def measure(self) -> str:
        """Сколько брать — человеческими словами.

        Штучное называем штуками: «1 шт.» понятнее, чем «120 г», а на полке
        человек берёт именно штуку.
        """
        if self.group == "питьё":
            return f"{self.grams:.0f} мл"
        # Штуками называем только то, что человек и правда считает штуками:
        # «два яблока» — понятно, «две с половиной моркови» — нет.
        if self.piece_g and (self.group == "фрукт" or self.code in COUNTED):
            pieces = round(self.grams / self.piece_g * 2) / 2
            word = PIECE_WORDS.get(pieces)
            if word:
                return f"{word} ({self.grams:.0f} г)"
        return f"{self.grams:.0f} г"


@dataclass(frozen=True)
class Cube:
    """Готовый набор: что купить, сколько это примерно и чем заменить."""

    items: tuple[Item, ...]
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    level: str
    craving: str
    title: str = ""
    swaps: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def signature(self) -> tuple[str, ...]:
        return tuple(sorted(item.code for item in self.items))

    @property
    def kcal_range(self) -> tuple[int, int]:
        """Диапазон, а не точное число: у каждой марки состав свой."""
        low = int(self.kcal // 50 * 50)
        return low, low + 50

    @property
    def protein_range(self) -> tuple[int, int]:
        low = int(self.protein_g // 5 * 5)
        return low, low + 5

    @property
    def protein_share(self) -> float:
        return self.protein_g * 4 / self.kcal if self.kcal else 0.0


def _allowed(product: Product, *, no_spoon: bool, exclude: set[str],
             vegan: bool, vegetarian: bool, gluten_free: bool) -> bool:
    """Годится ли продукт этому человеку прямо сейчас."""
    tags = set(product.tags.split(";")) if product.tags else set()
    # Ложечные продукты в режиме «без ложки» не показываем вовсе: человек
    # просил еду для машины, а не список с оговорками.
    if no_spoon and "spoon" in tags:
        return False
    if vegan and not product.vegan:
        return False
    if vegetarian and not product.vegetarian:
        return False
    if gluten_free and not product.gluten_free:
        return False
    if exclude & set(filter(None, product.allergens.split(";"))):
        return False
    return True


def _pool(products: dict[str, Product], *, basket: set[str] | None = None,
          **limits) -> dict[str, list[str]]:
    """Что доступно в каждой группе после всех ограничений.

    Если человек отметил, что у него уже в корзине, — берём только это:
    предлагать то, за чем надо возвращаться в другой конец магазина, значит
    не решать его задачу.
    """
    pool: dict[str, list[str]] = {}
    for group, codes in GROUPS.items():
        fit = [c for c in codes
               if c in products and (basket is None or c in basket)
               and _allowed(products[c], **limits)]
        if fit:
            pool[group] = fit
    return pool


def _nutrition(items: list[Item], products: dict[str, Product]) -> dict[str, float]:
    totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0}
    for item in items:
        product = products[item.code]
        share = item.grams / 100
        totals["kcal"] += product.kcal * share
        totals["protein_g"] += product.protein * share
        totals["fat_g"] += product.fat * share
        totals["carbs_g"] += product.carbs * share
    return totals


def _fit_portions(codes: list[str], products: dict[str, Product],
                  low: int, high: int) -> list[Item] | None:
    """Подогнать порции под нужную калорийность.

    Меняем все порции одним коэффициентом: так набор остаётся похожим на
    то, что реально лежит на полке, а не на «113 г банана».
    """
    base = [Item(code, products[code].name, PORTIONS[code], GROUP_OF[code],
                 products[code].gram_per_piece)
            for code in codes]
    kcal = _nutrition(base, products)["kcal"]
    if not kcal:
        return None

    target = (low + high) / 2
    scale = max(MIN_SCALE, min(MAX_SCALE, target / kcal))
    items = [Item(i.code, i.name,
                  _round_portion(i.grams * scale, i.group, products[i.code]),
                  i.group, i.piece_g)
             for i in base]

    total = _nutrition(items, products)["kcal"]
    # Выходить за границы режима нельзя: человек выбрал «пожевать», а не обед.
    return items if low * 0.85 <= total <= high * 1.15 else None


def _round_portion(grams: float, group: str, product: Product) -> float:
    """Округляем так, как продукт реально берут в руки.

    Штучное округляем до половины штуки: банан, яйцо и батончик покупают
    целиком, и «40 г батончика» человека только запутает.
    """
    piece = product.gram_per_piece
    if piece:
        halves = max(1, round(grams / (piece / 2)))
        return round(halves * piece / 2, 1)
    if group == "питьё":
        return max(50, round(grams / 50) * 50)
    if grams >= 100:
        return max(50, round(grams / 10) * 10)
    return max(5, round(grams / 5) * 5)


# Чего человеку сегодня не хватает. Приходит из дневника, а не от него самого:
# он пришёл поесть, а не считать белок.
NEED_PROTEIN = "protein"
NEED_FIBER = "fiber"

# Группы, которые дают клетчатку.
FIBER_GROUPS = frozenset({"фрукт", "овощ", "хруст", "орехи"})


def _shapes(level: str, craving: str, pool: dict[str, list[str]],
            needs: frozenset[str] = frozenset()) -> list[tuple[str, ...]]:
    """Формы наборов, годные для этого режима и настроения.

    Сначала привычные сочетания, потом всё остальное — чтобы «кефир с
    бананом» выпадал чаще, чем «сельдерей с тофу».
    """
    wanted = CRAVING_GROUPS.get(craving, frozenset())
    available = set(pool)

    def suits(shape: tuple[str, ...]) -> bool:
        if not set(shape) <= available:
            return False
        if not slots_ok(list(shape), level):
            return False
        # Не хватило клетчатки — в наборе обязан быть овощ или фрукт. Это
        # единственный способ её добрать, а не пожелание.
        if NEED_FIBER in needs and not (FIBER_GROUPS & set(shape)):
            return False
        return not wanted or bool(wanted & set(shape))

    favourites = [s for s in FAVOURITES if suits(s)]

    # Дальше — то, что правило разрешает, но в список любимых не попало.
    # Собираем перебором: белок плюс спутники.
    others: list[tuple[str, ...]] = []
    proteins = sorted(available & PROTEIN_GROUPS)
    companions = sorted(available - PROTEIN_GROUPS)
    _, _, _, _, max_items, _ = LEVELS[level]

    for first in proteins:
        for count in range(0, max_items):
            for combo in _combinations(companions, count):
                shape = (first, *combo)
                if suits(shape) and shape not in favourites:
                    others.append(shape)
    return favourites + others


def _combinations(items: list[str], count: int) -> list[tuple[str, ...]]:
    """Сочетания с повторами: два овоща в наборе — нормально."""
    if count == 0:
        return [()]
    out: list[tuple[str, ...]] = []
    for index, value in enumerate(items):
        for rest in _combinations(items[index:], count - 1):
            out.append((value, *rest))
    return out


def _score(cube: Cube, level: str, craving: str,
           needs: frozenset[str] = frozenset()) -> float:
    """Чем меньше, тем лучше."""
    _, low, high, _, _, _ = LEVELS[level]
    middle = (low + high) / 2
    penalty = abs(cube.kcal - middle) / middle

    # Белок — валюта этой функции: чем его больше, тем дольше человек сыт.
    penalty -= min(cube.protein_share, 0.4)

    if craving == "filling":
        penalty -= min(sum(i.grams for i in cube.items) / 1000, 0.5)
    if craving == "protein" or NEED_PROTEIN in needs:
        penalty -= min(cube.protein_g / 100, 0.4)
    return penalty


def build(products: dict[str, Product], *, level: str = "normal",
          craving: str = "random", no_spoon: bool = False,
          exclude: set[str] | None = None, vegan: bool = False,
          vegetarian: bool = False, gluten_free: bool = False,
          basket: set[str] | None = None, needs: frozenset[str] = frozenset(),
          recent: list[tuple[str, ...]] | None = None,
          limit: int = 3, rng: random.Random | None = None,
          _no_fallback: bool = False) -> list[Cube]:
    """Собрать несколько наборов под режим голода, настроение и недоборы дня.

    `needs` приходит из дневника: если сегодня мало белка или клетчатки,
    подбор учитывает это сам. Человек пришёл поесть, а не считать граммы.
    """
    if level not in LEVELS:
        level = "normal"
    rng = rng or random.Random()
    recent_set = set(recent or [])

    pool = _pool(products, basket=basket, no_spoon=no_spoon,
                 exclude=exclude or set(), vegan=vegan, vegetarian=vegetarian,
                 gluten_free=gluten_free)
    if not pool:
        return []

    _, low, high, _, _, _ = LEVELS[level]
    shapes = _shapes(level, craving, pool, needs)
    rng.shuffle(shapes)

    seen: set[tuple[str, ...]] = set()
    found: list[Cube] = []

    for shape in shapes[:400]:
        codes = [rng.choice(pool[group]) for group in shape]
        if len(set(codes)) != len(codes):
            continue
        # Категории сошлись — это ещё не значит, что такое едят.
        if not pairing_ok(codes):
            continue

        items = _fit_portions(codes, products, low, high)
        if items is None:
            continue

        totals = _nutrition(items, products)
        cube = Cube(items=tuple(items), level=level, craving=craving, **{
            "kcal": round(totals["kcal"], 1),
            "protein_g": round(totals["protein_g"], 1),
            "fat_g": round(totals["fat_g"], 1),
            "carbs_g": round(totals["carbs_g"], 1),
        })

        # «Почти нормальный приём пищи» без белка — не приём пищи.
        if level == "meal" and cube.protein_share < MIN_PROTEIN_SHARE:
            continue
        if cube.signature in seen or cube.signature in recent_set:
            continue

        seen.add(cube.signature)
        found.append(cube)
        if len(found) >= limit * 4:
            break

    if not found and needs and not _no_fallback:
        # Под жёсткое требование могло ничего не собраться. Пустой экран
        # человеку полезен меньше, чем набор без клетчатки.
        return build(products, level=level, craving=craving, no_spoon=no_spoon,
                     exclude=exclude, vegan=vegan, vegetarian=vegetarian,
                     gluten_free=gluten_free, basket=basket,
                     recent=recent, limit=limit, rng=rng)

    found.sort(key=lambda c: _score(c, level, craving, needs))
    return [_decorate(cube, pool) for cube in _varied(found, limit)]


def _varied(cubes: list[Cube], limit: int) -> list[Cube]:
    """Выбрать несколько наборов так, чтобы они отличались.

    Три варианта подряд на одном и том же тофу — это один вариант,
    показанный трижды: человек решит, что бот сломался.
    """
    chosen: list[Cube] = []
    used: set[str] = set()

    for cube in cubes:
        proteins = {i.code for i in cube.items if i.group in PROTEIN_GROUPS}
        if proteins & used:
            continue
        chosen.append(cube)
        used |= proteins
        if len(chosen) >= limit:
            return chosen

    # Разных белков не хватило — дополняем чем есть, лишь бы не пусто.
    for cube in cubes:
        if cube not in chosen:
            chosen.append(cube)
        if len(chosen) >= limit:
            break
    return chosen


def _decorate(cube: Cube, pool: dict[str, list[str]]) -> Cube:
    """Дописать название и подсказки «чем заменить»."""
    swaps = {}
    for item in cube.items:
        alternatives = [c for c in pool.get(item.group, []) if c != item.code]
        if alternatives:
            swaps[item.code] = tuple(alternatives[:3])
    return Cube(items=cube.items, kcal=cube.kcal, protein_g=cube.protein_g,
                fat_g=cube.fat_g, carbs_g=cube.carbs_g, level=cube.level,
                craving=cube.craving, title=title_for(cube), swaps=swaps)


# --- Названия карточек -----------------------------------------------------
# Не «греческий йогурт + банан», а что-то, что не стыдно показать другому.
# Название обязано соответствовать составу: карточка «Банановая страховка»
# без банана выглядит как ошибка, потому что это она и есть.
def _named(codes: set[str], groups: set[str]) -> str | None:
    if "banana" in codes and groups & {"орехи", "сладкийхруст"}:
        return "Банановая страховка"
    if "kefir" in codes or "ryazhenka" in codes:
        return "Кефирный экспресс"
    if "батончик" in groups:
        return "Батончик и точка"
    if "творожное" in groups:
        return "Творожный антиголод"
    if "растбелок" in groups:
        return "Белковая подушка"
    if "мясо" in groups and groups & {"хруст", "овощ"}:
        return "Солёный спасатель"
    if "мясо" in groups:
        return "Белок найден"
    if "сыр" in groups and "apple" in codes:
        return "Сыр и яблоко, классика"
    if "сыр" in groups:
        return "Сырный вопрос закрыт"
    if "питьё" in groups:
        return "Выпил и поехал"
    if groups & {"хруст", "орехи"}:
        return "Хруст и порядок"
    return None


# Если ничего не подошло — берём из запасных, но не случайно: один и тот же
# набор должен называться одинаково, иначе человек решит, что это разное.
SPARE = ("Не съем кассира", "До ужина доживу", "Съела и побежала",
         "Перекус без драмы", "Мне некогда готовить", "Магазинный набор")


def title_for(cube: Cube) -> str:
    codes = {item.code for item in cube.items}
    groups = {item.group for item in cube.items}
    return _named(codes, groups) or SPARE[
        sum(map(ord, "".join(cube.signature))) % len(SPARE)
    ]


# --- «Я уже в магазине» ----------------------------------------------------
# Человек стоит у полки. Вопрос ровно один, ответов сразу три: попроще,
# посытнее и запасной — чтобы не гонять его по кругу «а покажи другое».
SHOP_LABELS = ("Самый простой", "Посытнее", "Запасной")


def shop_offers(products: dict[str, Product], *, craving: str = "random",
                rng: random.Random | None = None,
                **limits) -> list[tuple[str, Cube]]:
    """Три варианта на один вопрос: простой, сытный и запасной."""
    rng = rng or random.Random()

    light = build(products, level="normal", craving=craving, limit=8,
                  rng=rng, **limits)
    heavy = build(products, level="hungry", craving=craving, limit=8,
                  rng=rng, **limits)

    offers: list[tuple[str, Cube]] = []
    used: set[str] = set()

    def take(label: str, options: list[Cube], key=None) -> None:
        for cube in sorted(options, key=key) if key else options:
            proteins = {i.code for i in cube.items if i.group in PROTEIN_GROUPS}
            if proteins & used or cube.signature in {c.signature for _, c in offers}:
                continue
            offers.append((label, cube))
            used.update(proteins)
            return

    # Простой — тот, где меньше всего бегать по магазину.
    take(SHOP_LABELS[0], light, key=lambda c: len(c.items))
    take(SHOP_LABELS[1], heavy)
    take(SHOP_LABELS[2], light + heavy)

    # Если разных белков не нашлось, лучше показать хоть что-то, чем пусто.
    if not offers:
        offers = [(SHOP_LABELS[0], cube) for cube in light[:1]]
    return offers


def level_for(kcal_left: float | None) -> str:
    """Подсказать режим по остатку калорий, если он известен."""
    if kcal_left is None:
        return "normal"
    for name in ("light", "normal", "hungry", "meal"):
        _, low, high, _, _, _ = LEVELS[name]
        if kcal_left <= high:
            return name
    return "meal"


__all__ = ["Cube", "GROUP_OF", "Item", "MIN_PROTEIN_SHARE", "NEED_FIBER",
           "NEED_PROTEIN", "REMEMBER", "SHOP_LABELS", "build", "level_for",
           "shop_offers", "title_for"]
