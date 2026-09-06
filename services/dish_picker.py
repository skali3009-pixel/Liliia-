"""Подбор блюда под остаток нормы человека.

Работает только по справочнику: ничего не выдумывает и никуда не ходит.
Порядок такой — сначала отсеиваем то, что человеку нельзя, потом подгоняем
порцию под бюджет приёма, потом сортируем по тому, насколько вариант
уместен именно сейчас.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Meal, User
from services import catalogue
from services.catalogue import CachedDish
from services import method

logger = logging.getLogger(__name__)

# Насколько можно растянуть или ужать авторскую порцию. Шире — это уже
# другое блюдо, а не порция того же самого.
SCALE_MIN, SCALE_MAX = 0.7, 1.3
# Допуск по бюджету приёма после пересчёта порции.
BUDGET_TOLERANCE = 0.25
# Сколько дней подряд не повторять блюдо.
REPEAT_DAYS = 3

DIET_FIELD = {"vegan": "vegan", "vegetarian": "vegetarian", "gluten_free": "gluten_free"}


@dataclass
class Pick:
    """Готовый вариант: блюдо, пересчитанная порция и её КБЖУ."""

    dish: CachedDish
    scale: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float
    weight_g: float
    reason: str = ""
    components: list[tuple[str, float, str]] = field(default_factory=list)
    preps: list[str] = field(default_factory=list)

    @property
    def author(self) -> bool:
        return self.dish.author

    def to_dict(self) -> dict:
        return {
            "code": self.dish.code,
            "name": self.dish.name,
            "author": self.dish.author,
            "source": self.dish.source,
            "minutes": self.dish.minutes,
            "scale": round(self.scale, 2),
            "calories": round(self.kcal),
            "protein_g": round(self.protein_g, 1),
            "fat_g": round(self.fat_g, 1),
            "carbs_g": round(self.carbs_g, 1),
            "fiber_g": round(self.fiber_g, 1),
            "weight_g": round(self.weight_g),
            "reason": self.reason,
            "preps": self.preps,
            "estimated": self.dish.estimated,
            "no_cook": self.dish.no_cook,
        }


def _allergen_words(raw: str | None) -> set[str]:
    """Аллергии человек пишет свободным текстом — разбираем по словам."""
    if not raw:
        return set()
    cleaned = raw.lower().replace(",", " ").replace(";", " ").replace("/", " ")
    return {word.strip(".!") for word in cleaned.split() if len(word) > 2}


def _blocked(haystack: str, words: set[str]) -> bool:
    """Продукт под запретом, если совпал с аллергией по названию или метке."""
    return any(word in haystack for word in words)


def scale_for(dish: CachedDish, budget: float) -> float | None:
    """Коэффициент порции под бюджет приёма. None — блюдо не подходит."""
    if dish.kcal <= 0 or budget <= 0:
        return None
    raw = budget / dish.kcal
    scale = min(SCALE_MAX, max(SCALE_MIN, raw))
    # После зажима в границы проверяем, попали ли в допуск по калориям.
    if abs(dish.kcal * scale - budget) > budget * BUDGET_TOLERANCE:
        return None
    return round(scale, 2)


def _scaled(dish: CachedDish, scale: float) -> Pick:
    return Pick(
        dish=dish, scale=scale,
        kcal=dish.kcal * scale, protein_g=dish.protein_g * scale,
        fat_g=dish.fat_g * scale, carbs_g=dish.carbs_g * scale,
        fiber_g=dish.fiber_g * scale, weight_g=dish.weight_g * scale,
    )


async def _recent_codes(session: AsyncSession, user_id: int, days: int = REPEAT_DAYS) -> set[str]:
    """Что человек уже ел в последние дни — чтобы не предлагать то же самое."""
    since = datetime.utcnow() - timedelta(days=days)
    names = (await session.execute(
        select(Meal.name).where(Meal.user_id == user_id, Meal.logged_at >= since)
    )).scalars().all()
    return {name.strip().lower() for name in names}


async def candidates(session: AsyncSession, user: User, meal_type: str,
                     *, no_cook: bool = False) -> list[CachedDish]:
    """Блюда, которые этому человеку в принципе можно показывать.

    Справочник берётся из памяти: он не меняется во время работы, и ходить
    за ним в базу на каждое нажатие незачем.

    `no_cook` — режим «готовить негде»: остаются только комбо, которые
    собираются из купленного в магазине.
    """
    dishes = await catalogue.for_meal(session, meal_type)
    if no_cook:
        dishes = [d for d in dishes if d.no_cook]

    words = _allergen_words(user.allergies)
    diet = user.diet_type.value if user.diet_type else "regular"
    diet_field = DIET_FIELD.get(diet)
    if not words and not diet_field:
        return dishes

    allowed: list[CachedDish] = []
    for dish in dishes:
        ok = True
        for item in dish.components:
            if item.optional:
                continue
            if words and _blocked(item.haystack, words):
                ok = False
                break
            if diet_field and not getattr(item, diet_field):
                ok = False
                break
        if ok:
            allowed.append(dish)
    return allowed


async def prep_names(session: AsyncSession, dish) -> list[str]:
    """Названия заготовок, из которых собирается блюдо."""
    if not isinstance(dish, CachedDish):
        cached = await catalogue.by_code(session, dish.code)
        if cached is None:
            return []
        dish = cached
    return list(dish.prep_titles)


def rank(picks: list[Pick], *, budget: float, gap: str | None,
         recent: set[str], have: set[str] | None = None,
         expiring: set[str] | None = None) -> list[Pick]:
    """Отсортировать варианты: чем меньше счёт, тем уместнее сейчас.

    `have` — заготовки, которые у человека реально есть, `expiring` — те,
    что подходят к концу срока. Блюдо, собираемое из готового, почти не
    требует работы, и это самое ценное, что можно предложить вечером.
    """
    def score(pick: Pick) -> float:
        value = abs(pick.kcal - budget) / max(budget, 1)
        # Закрыть главный недобор дня важнее, чем попасть в калории до единицы.
        if gap == "protein_g" and pick.protein_g >= 25:
            value -= 0.25
        if gap == "fiber_g" and pick.fiber_g >= 7:
            value -= 0.25
        # Её рецепт при прочих равных идёт выше: это ядро сервиса.
        if pick.dish.author:
            value -= 0.05
        if pick.dish.name.strip().lower() in recent:
            value += 0.5
        # Долгая готовка вечером — так себе предложение, а собранное из
        # заготовок наоборот: это её главный способ экономить время.
        value += min(pick.dish.minutes, 60) / 600
        if pick.preps:
            value -= 0.08
        # А если заготовка не просто упомянута, а реально стоит в холодильнике,
        # это лучшее предложение из возможных: готовить почти нечего. И тем
        # более если она подходит к концу срока.
        if have and set(pick.dish.prep_codes) & have:
            value -= 0.4
        if expiring and set(pick.dish.prep_codes) & expiring:
            value -= 0.5
        return value

    return sorted(picks, key=score)


def explain(pick: Pick, *, budget: float, gap: str | None,
            have: set[str] | None = None, expiring: set[str] | None = None) -> str:
    """Одна фраза, чем вариант хорош именно сейчас."""
    codes = set(pick.dish.prep_codes)
    if expiring and codes & expiring:
        return "Заготовку лучше доесть сегодня — это она"
    if have and codes & have:
        return "Собирается из того, что уже готово"
    if pick.preps and pick.dish.minutes <= 12:
        return f"Почти всё готово — собрать за {pick.dish.minutes} минут"
    if gap == "protein_g" and pick.protein_g >= 25:
        return f"Закроет недобор белка — {pick.protein_g:.0f} г"
    if gap == "fiber_g" and pick.fiber_g >= 7:
        return f"Много клетчатки — {pick.fiber_g:.0f} г"
    if abs(pick.kcal - budget) <= budget * 0.08:
        return f"Точно в бюджет приёма — {pick.kcal:.0f} ккал"
    if pick.dish.minutes <= 15:
        return f"Готовится {pick.dish.minutes} минут"
    return f"{pick.kcal:.0f} ккал на порцию"


async def pick_dishes(session: AsyncSession, user: User, *, meal_type: str,
                      budget: float, gap: str | None = None, limit: int = 3,
                      no_cook: bool = False) -> tuple[list[Pick], list[Pick]]:
    """Подобрать блюда под приём пищи.

    Возвращает (подошедшие, ближайшие). Второй список не пустой только когда
    первый пуст: это честный ответ «точного варианта нет, вот что рядом»
    вместо выдуманного блюда.
    """
    allowed = await candidates(session, user, meal_type, no_cook=no_cook)
    recent = await _recent_codes(session, user.id)

    # Что реально стоит в холодильнике: из этого блюдо собирается почти без
    # работы, и такие варианты должны идти первыми.
    from services.preps import mine as my_preps

    fridge = await my_preps(session, user.id)
    have = {item.code for item in fridge if not item.gone}
    expiring = {item.code for item in fridge if item.expiring and not item.gone}

    fitted, near = [], []
    for dish in allowed:
        scale = scale_for(dish, budget)
        if scale is None:
            # Ближайшее — с зажатой в границы порцией, чтобы было что показать.
            fallback = min(SCALE_MAX, max(SCALE_MIN, budget / dish.kcal)) if dish.kcal else 1
            near.append(_scaled(dish, round(fallback, 2)))
            continue
        fitted.append(_scaled(dish, scale))

    for pick in fitted:
        pick.preps = await prep_names(session, pick.dish)

    ranked = rank(fitted, budget=budget, gap=gap, recent=recent,
                  have=have, expiring=expiring)[:limit]
    for pick in ranked:
        pick.reason = explain(pick, budget=budget, gap=gap,
                              have=have, expiring=expiring)

    if ranked:
        return ranked, []

    closest = sorted(near, key=lambda p: abs(p.kcal - budget))[:limit]
    for pick in closest:
        pick.preps = await prep_names(session, pick.dish)
        over = pick.kcal - budget
        pick.reason = (f"На {abs(over):.0f} ккал {'больше' if over > 0 else 'меньше'} "
                       f"бюджета приёма")
    return [], closest


async def components_of(session: AsyncSession, dish, scale: float = 1.0) -> list[dict]:
    """Состав блюда на одну порцию с учётом пересчёта."""
    if not isinstance(dish, CachedDish):
        # Тесты и старый код передают сюда объект из базы — берём его по коду.
        cached = await catalogue.by_code(session, dish.code)
        if cached is None:
            return []
        dish = cached

    out: list[dict] = []
    for item in dish.components:
        grams = item.grams / (dish.portions or 1) * scale
        if item.countable and item.gram_per_piece:
            # Штуки округляем до целого: яйцо не бывает 1,4 штуки.
            pieces = max(1, round(grams / item.gram_per_piece))
            grams = pieces * item.gram_per_piece
        out.append({
            "name": item.name,
            "grams": round(grams) if not item.is_seasoning else 0,
            "raw": item.raw_amount,
            "seasoning": item.is_seasoning,
            "role": item.role,
        })
    return out


__all__ = ["BUDGET_TOLERANCE", "Pick", "REPEAT_DAYS", "SCALE_MAX", "SCALE_MIN",
           "candidates", "components_of", "explain", "pick_dishes", "prep_names",
           "rank", "scale_for"]
