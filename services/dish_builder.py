"""Сборка блюда сверх меню — по принципам Анастасии и только из её продуктов.

Когда в справочнике нет ничего подходящего (веган, жёсткая аллергия, узкий
бюджет), бот не должен разводить руками — но и выдумывать блюда «из
интернета» тоже нельзя. Поэтому здесь строгий порядок:

1. Модель получает список разрешённых продуктов и правила метода и
   возвращает ТОЛЬКО состав: коды продуктов и граммы.
2. Любой код не из списка — состав отбрасывается целиком.
3. КБЖУ считаем сами по своей таблице. Модель к цифрам не допускается:
   именно там она врёт чаще всего.
4. Состав проходит проверку методом (белок, овощи, размеры порций).
   Не прошёл — вторая попытка, потом честный отказ.
"""

from __future__ import annotations

import json
import logging

import anthropic

import config
from models import Product, User
from services import method
from services.food_vision import FoodRecognitionError, VisionNotConfigured, get_client

logger = logging.getLogger(__name__)

MAX_TOKENS = 1200
MAX_ATTEMPTS = 2

MEAL_RU = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин", "snack": "перекус"}

SYSTEM_PROMPT = (
    "Ты собираешь блюдо по методу нутрициолога Анастасии Явхуты.\n"
    "\n"
    "Её принципы, которым нужно следовать буквально:\n"
    "- В каждом приёме есть источник белка: он держит сытость и бережёт мышцы.\n"
    "- Половина тарелки — овощи и зелень, четверть — белок, четверть — крупа.\n"
    "- Порция белка 100–220 г, крупа 40–90 г в сухом виде, добавленный жир "
    "5–20 г (ложка масла, не больше).\n"
    "- Ужин легче обеда: белок и овощи, поменьше быстрых углеводов.\n"
    "- Перекус — это стакан смузи до 200 мл или йогурт с фруктом, а не тарелка.\n"
    "- Соус собирается по формуле: йогурт + масло + соль; или йогурт + горчица "
    "+ лимон + мёд; или йогурт + ореховая паста + соевый соус + лимон.\n"
    "- Блюдо должно готовиться просто: запечь, отварить, обжарить, смешать.\n"
    "\n"
    "ЖЁСТКИЕ ОГРАНИЧЕНИЯ:\n"
    "- Используй ТОЛЬКО продукты из списка, который тебе дали, и только их коды. "
    "Продукт не из списка — грубая ошибка.\n"
    "- НЕ указывай калории и БЖУ. Их считает сервер по своей таблице. "
    "Твоё дело — состав в граммах и способ приготовления.\n"
    "- Граммы указывай для сырого/сухого продукта, как в рецептах: крупа сухая, "
    "мясо сырое.\n"
    "- Название и шаги — на русском языке, коротко и по делу."
)

BUILD_TOOL = {
    "name": "build_dish",
    "description": "Собрать одно блюдо из разрешённых продуктов.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Название блюда по-русски"},
            "minutes": {"type": "integer", "description": "Сколько минут готовить"},
            "instructions": {"type": "string", "description": "Как приготовить, 2-4 фразы"},
            "components": {
                "type": "array",
                "minItems": 3,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Код продукта из списка"},
                        "grams": {"type": "number", "description": "Граммы на одну порцию"},
                    },
                    "required": ["code", "grams"],
                },
            },
        },
        "required": ["name", "minutes", "instructions", "components"],
    },
}


def allowed_products(products: list[Product], *, diet: str, allergy_words: set[str]
                     ) -> list[Product]:
    """Продукты, которые этому человеку можно предлагать."""
    from services.dish_picker import DIET_FIELD, _blocked

    field = DIET_FIELD.get(diet)
    out = []
    for product in products:
        if field and not getattr(product, field):
            continue
        if allergy_words and _blocked(product, allergy_words):
            continue
        out.append(product)
    return out


def catalogue(products: list[Product]) -> str:
    """Список продуктов для модели: код, название, роль. Без КБЖУ — они ей не нужны."""
    lines = []
    for product in products:
        if product.is_seasoning:
            continue
        lines.append(f"{product.code} — {product.name} ({product.role})")
    return "\n".join(lines)


def build_request(*, meal_type: str, budget: float, gap: str | None,
                  products: list[Product], avoid: list[str]) -> str:
    parts = [
        f"Собери {MEAL_RU.get(meal_type, meal_type)} примерно на {budget:.0f} ккал.",
        method.plate_hint(meal_type),
    ]
    if gap == "protein_g":
        parts.append("У человека сегодня недобор белка — сделай его основой блюда.")
    if gap == "fiber_g":
        parts.append("У человека недобор клетчатки — добавь овощи, бобовые или зелень.")
    if avoid:
        parts.append("Не повторяй то, что уже было на днях: " + ", ".join(avoid[:6]) + ".")
    parts.append("\nРазрешённые продукты (только эти коды):\n" + catalogue(products))
    return "\n".join(parts)


def _parse(response) -> dict | None:
    for block in response.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "build_dish":
            return block.input
    return None


def validate(raw: dict, products: dict[str, Product], *, meal_type: str
             ) -> tuple[list[dict], list[method.Violation]]:
    """Проверить состав: продукты из списка, порции в рамках метода.

    Возвращает (состав, нарушения). Неизвестный продукт — не нарушение,
    а отказ: такой состав вообще не имеет смысла обсуждать.
    """
    components: list[dict] = []
    for item in raw.get("components", []):
        code = str(item.get("code", "")).strip()
        product = products.get(code)
        if product is None:
            raise FoodRecognitionError(f"Модель предложила продукт вне списка: {code!r}")
        grams = float(item.get("grams") or 0)
        if grams < 0 or grams > 1000:
            raise FoodRecognitionError(f"Неправдоподобный вес: {grams} г")
        components.append({"product_code": code, "grams": grams,
                           "role": product.role, "raw_amount": f"{grams:.0f} г"})

    if not components:
        raise FoodRecognitionError("Пустой состав")

    totals = nutrition(components, products)
    problems = method.check(meal_type=meal_type, components=components,
                            kcal=totals["kcal"], protein_g=totals["protein_g"])
    return components, problems


def nutrition(components: list[dict], products: dict[str, Product]) -> dict[str, float]:
    """КБЖУ состава. Считаем мы, а не модель — это принципиально."""
    from seed.nutrition.loader import nutrition_of

    return nutrition_of(components, products, 1.0)


async def build_dish(user: User, *, meal_type: str, budget: float,
                     products: list[Product], gap: str | None = None,
                     avoid: list[str] | None = None, on_usage=None) -> dict:
    """Собрать одно блюдо. Бросает FoodRecognitionError, если не вышло."""
    diet = user.diet_type.value if user.diet_type else "regular"
    from services.dish_picker import _allergen_words

    pool = allowed_products(products, diet=diet,
                            allergy_words=_allergen_words(user.allergies))
    if len(pool) < 10:
        raise FoodRecognitionError("Слишком мало разрешённых продуктов для сборки")

    by_code = {p.code: p for p in pool}
    request = build_request(meal_type=meal_type, budget=budget, gap=gap,
                            products=pool, avoid=avoid or [])
    last_error = "не удалось собрать блюдо"

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await get_client().messages.create(
                # Здесь важнее рассуждение, а вызовов на порядок меньше, чем
                # распознаваний фото, — поэтому модель посильнее.
                model=config.BUILD_MODEL,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": SYSTEM_PROMPT,
                         "cache_control": {"type": "ephemeral"}}],
                tools=[BUILD_TOOL],
                tool_choice={"type": "tool", "name": "build_dish"},
                messages=[{"role": "user", "content": request}],
            )
        except anthropic.AuthenticationError:
            raise VisionNotConfigured("Ключ Anthropic не принят.") from None
        except anthropic.APIError as error:
            logger.warning("Сборка блюда: ошибка запроса — %s", error)
            raise FoodRecognitionError("Сервис подбора сейчас недоступен") from None

        if on_usage is not None:
            on_usage(getattr(response, "usage", None))

        raw = _parse(response)
        if raw is None:
            last_error = "модель не вернула состав"
            continue

        try:
            components, problems = validate(raw, by_code, meal_type=meal_type)
        except FoodRecognitionError as error:
            last_error = str(error)
            logger.info("Сборка блюда отклонена: %s", last_error)
            continue

        if problems:
            last_error = "; ".join(f"{p.rule}: {p.detail}" for p in problems)
            logger.info("Сборка блюда не прошла проверку: %s", last_error)
            request_retry = request + (
                "\n\nПредыдущая попытка нарушила правила: " + last_error +
                ". Собери заново с учётом этого."
            )
            request = request_retry
            continue

        totals = nutrition(components, by_code)
        return {
            "name": str(raw.get("name", "Блюдо")).strip()[:120],
            "minutes": max(5, min(int(raw.get("minutes") or 20), 120)),
            "instructions": str(raw.get("instructions", "")).strip()[:800],
            "components": components,
            **totals,
        }

    raise FoodRecognitionError(f"Не получилось собрать блюдо: {last_error}")


__all__ = ["BUILD_TOOL", "allowed_products", "build_dish", "build_request",
           "catalogue", "nutrition", "validate"]
