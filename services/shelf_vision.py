"""«Сфоткай полку»: модель называет продукты, наборы собираем сами.

Зачем отдельный сервис, если распознавание еды уже есть. Задание модели
другое. У блюда мы спрашиваем «сколько тут КБЖУ» и вынуждены доверять
ответу целиком. У полки мы не спрашиваем ничего, кроме названий: модель
только показывает пальцем, а калории, порции и сочетания считает Кубик по
своим правилам и по нашему справочнику.

Отсюда главное ограничение: модель отвечает не текстом и не свободным
названием, а кодом продукта из нашего же списка. Всё, чего в списке нет,
до Кубика не доходит — ни выдуманный код, ни «авокадо», которого мы не
умеем считать. Такое уходит в other и показывается человеку отдельной
строкой, чтобы он понимал, что бот это видел, но посчитать не может.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import config
from seed.nutrition.cube_rules import GROUP_INDEX
from services.food_vision import (
    FoodRecognitionError,
    friendly_errors,
    get_client,
)
from utils import images

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024

# Больше двадцати пяти отметок человек всё равно не разберёт глазами, а
# сборке набора это ничего не добавляет: Кубику хватает нескольких групп.
MAX_FOUND = 25
# Незнакомое показываем как справку, а не как список покупок.
MAX_OTHER = 6
MAX_OTHER_LEN = 40

SYSTEM_PROMPT = (
    "Ты смотришь на фотографию полки: холодильник, витрина магазина, стол или "
    "пакет с покупками. Твоя задача — назвать, какие продукты на ней видно.\n"
    "\n"
    "Правила:\n"
    "- Отвечай кодами из списка ниже. Кодов не из списка не бывает.\n"
    "- Называй только то, что действительно видно. Не додумывай: если банка "
    "или пачка не читается — пропусти её.\n"
    "- Один продукт — один код, даже если его на полке несколько штук.\n"
    "- Не подбирай «похожее»: если видно ряженку, это ryazhenka, а не kefir.\n"
    "- Еду, которую видно, но которой нет в списке, перечисли в other русскими "
    "названиями (например «авокадо», «пельмени»). Коротко, без описаний.\n"
    "- Если еды на фото нет вообще — верни оба списка пустыми.\n"
    "\n"
    "Всегда вызывай инструмент record_shelf. Не отвечай обычным текстом."
)


@dataclass(frozen=True)
class Shelf:
    """Что модель разглядела на полке."""

    codes: tuple[str, ...]
    other: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.codes)


def vocabulary(names: dict[str, str]) -> dict[str, str]:
    """Словарь распознавания: только то, из чего Кубик умеет собирать наборы.

    Справочник продуктов шире Кубика — в нём есть крупы, масло, то, что надо
    варить. Узнавать их на полке бессмысленно: собрать из них перекус без
    приборов всё равно нельзя.
    """
    return {code: names[code] for code in sorted(GROUP_INDEX) if code in names}


def _prompt(known: dict[str, str]) -> str:
    lines = "\n".join(f"{code} — {name}" for code, name in known.items())
    return f"{SYSTEM_PROMPT}\nСписок продуктов:\n{lines}"


def _tool(known: dict[str, str]) -> dict[str, Any]:
    return {
        "name": "record_shelf",
        "description": "Записать, какие продукты видно на фотографии полки.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "found": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(known)},
                    "description": "Коды продуктов со списка, которые видно на фото",
                },
                "other": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Русские названия еды, которой нет в списке",
                },
            },
            "required": ["found", "other"],
            "additionalProperties": False,
        },
    }


def _build_shelf(payload: dict[str, Any], known: dict[str, str]) -> Shelf:
    """Разобрать ответ модели, выбросив всё, чего мы не знаем.

    Схема со списком кодов уже не должна пропускать чужое, но проверяем ещё
    раз здесь: набор собирается из этих кодов, и выдуманный код превратился
    бы в продукт, которого человек не покупал.
    """
    codes: list[str] = []
    for raw in payload.get("found") or []:
        code = str(raw).strip()
        if code not in known:
            logger.warning("Модель назвала неизвестный продукт: %.40s", code)
            continue
        if code not in codes:
            codes.append(code)

    other: list[str] = []
    for raw in payload.get("other") or []:
        name = str(raw).strip()[:MAX_OTHER_LEN]
        if name and name not in other:
            other.append(name)

    return Shelf(codes=tuple(codes[:MAX_FOUND]), other=tuple(other[:MAX_OTHER]))


async def _request(content: list[dict[str, Any]], known: dict[str, str]):
    return await get_client().messages.create(
        model=config.VISION_MODEL,
        max_tokens=MAX_TOKENS,
        # Инструкция вместе со списком продуктов меняется только при правке
        # справочника — просим её закэшировать: чтение из кэша в десять раз
        # дешевле обычного входа, а список длинный.
        system=[{"type": "text", "text": _prompt(known),
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_tool(known)],
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": content}],
    )


async def recognize(image_bytes: bytes, names: dict[str, str], *,
                    media_type: str = "image/jpeg", on_usage=None) -> Shelf:
    """Найти на фото полки продукты из нашего справочника.

    `names` — справочник «код продукта → название»; лишнее отсекается сразу.
    `on_usage` вызывается с расходом токенов: деньги считает тот, кто знает,
    чей это запрос.
    """
    known = vocabulary(names)
    if not known:
        raise FoodRecognitionError(
            "Справочник продуктов пуст — распознавать полку не из чего."
        )

    # Полка — это много мелких этикеток, но и здесь 1024 пикселя хватает:
    # мы узнаём продукт по форме и цвету упаковки, а не читаем состав.
    encoded = base64.standard_b64encode(images.for_food(image_bytes)).decode("utf-8")
    content = [
        {"type": "image",
         "source": {"type": "base64", "media_type": media_type, "data": encoded}},
        {"type": "text", "text": "Что из списка есть на этой полке?"},
    ]

    with friendly_errors():
        response = await _request(content, known)

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        logger.warning("Модель не вызвала инструмент, stop_reason=%s", response.stop_reason)
        raise FoodRecognitionError(
            "Не получилось разобрать ответ модели. Пришли фото ещё раз."
        )

    shelf = _build_shelf(dict(tool_use.input), known)
    if on_usage is not None:
        on_usage(getattr(response, "usage", None))
    return shelf


__all__ = ["MAX_FOUND", "MAX_OTHER", "SYSTEM_PROMPT", "Shelf", "recognize", "vocabulary"]
