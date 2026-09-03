"""Распознавание еды через Claude: по фото (vision) и по текстовому описанию.

Ответ модели получаем не свободным текстом, а через вызов инструмента
`record_food_analysis` со `strict: true` — так JSON гарантированно
соответствует схеме и его не нужно вытаскивать регулярками из текста.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import asdict, dataclass
from typing import Any

import anthropic

import config

logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

MAX_TOKENS = 1024

SYSTEM_PROMPT = (
    "Ты — нутрициолог, который оценивает КБЖУ блюда по фотографии или описанию.\n"
    "\n"
    "Правила:\n"
    "- Оценивай ВСЮ порцию, которая видна на фото (или описана текстом), а не 100 г продукта.\n"
    "- Вес порции оценивай по визуальным ориентирам: размер тарелки (обычно 24-27 см), "
    "столовых приборов, стакана, руки.\n"
    "- Если на фото несколько блюд — объединяй их в одно название и суммируй КБЖУ.\n"
    "- Учитывай способ приготовления (жарка на масле добавляет жиры) и заправки/соусы.\n"
    "- Название блюда — на русском языке, коротко (до 60 символов).\n"
    "- confidence: high — блюдо и порция очевидны; medium — есть сомнения в составе или весе; "
    "low — плохо видно, много скрытых ингредиентов.\n"
    "- В comment пиши одну короткую фразу: что именно ты предположил "
    "(например, «оценил как 2 сырника со сметаной»). Без вступлений.\n"
    "- Если на фото нет еды (или описание не про еду) — верни recognized=false "
    "и объясни это в comment.\n"
    "\n"
    "Всегда вызывай инструмент record_food_analysis. Не отвечай обычным текстом."
)

FOOD_ANALYSIS_TOOL: dict[str, Any] = {
    "name": "record_food_analysis",
    "description": "Записать распознанное блюдо, вес порции и её КБЖУ.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "recognized": {
                "type": "boolean",
                "description": "true, если на фото/в описании есть еда и её удалось оценить",
            },
            "name": {
                "type": "string",
                "description": "Название блюда на русском, до 60 символов. Пустая строка, если recognized=false",
            },
            "weight_g": {
                "type": "number",
                "description": "Оценка веса всей порции в граммах",
            },
            "calories": {"type": "number", "description": "Калорийность всей порции, ккал"},
            "protein_g": {"type": "number", "description": "Белки всей порции, г"},
            "fat_g": {"type": "number", "description": "Жиры всей порции, г"},
            "carbs_g": {"type": "number", "description": "Углеводы всей порции, г"},
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Насколько модель уверена в оценке",
            },
            "comment": {
                "type": "string",
                "description": "Одна короткая фраза о сделанных предположениях",
            },
        },
        "required": [
            "recognized",
            "name",
            "weight_g",
            "calories",
            "protein_g",
            "fat_g",
            "carbs_g",
            "confidence",
            "comment",
        ],
        "additionalProperties": False,
    },
}

CONFIDENCE_RU = {"high": "высокая", "medium": "средняя", "low": "низкая"}


class FoodRecognitionError(Exception):
    """Не удалось получить корректный ответ от модели."""


class FoodNotRecognized(FoodRecognitionError):
    """На фото/в описании нет еды — показываем пользователю пояснение модели."""


@dataclass(frozen=True)
class FoodAnalysis:
    """Результат распознавания одной порции."""

    name: str
    weight_g: float
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float
    confidence: str
    comment: str

    def to_dict(self) -> dict[str, Any]:
        """Для хранения в FSM-хранилище (там нужны простые типы)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FoodAnalysis":
        return cls(**data)


def _positive(value: Any) -> float:
    """Числа из ответа модели: отрицательных/нечисловых значений быть не должно."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(number, 0.0)


def _build_analysis(payload: dict[str, Any]) -> FoodAnalysis:
    if not payload.get("recognized"):
        raise FoodNotRecognized(
            payload.get("comment") or "На фото не видно еды. Пришли фото блюда или опиши его текстом."
        )

    name = str(payload.get("name") or "").strip()
    if not name:
        raise FoodRecognitionError("Модель не вернула название блюда")

    return FoodAnalysis(
        name=name[:60],
        weight_g=_positive(payload.get("weight_g")),
        calories=_positive(payload.get("calories")),
        protein_g=_positive(payload.get("protein_g")),
        fat_g=_positive(payload.get("fat_g")),
        carbs_g=_positive(payload.get("carbs_g")),
        confidence=str(payload.get("confidence") or "medium"),
        comment=str(payload.get("comment") or "").strip(),
    )


async def _analyze(content: list[dict[str, Any]]) -> FoodAnalysis:
    response = await _client.messages.create(
        model=config.VISION_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[FOOD_ANALYSIS_TOOL],
        # tool_choice="auto" + явная инструкция в системном промпте: принудительный
        # выбор инструмента несовместим с thinking, который у современных моделей
        # включён по умолчанию.
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": content}],
    )

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        logger.warning("Модель не вызвала инструмент, stop_reason=%s", response.stop_reason)
        raise FoodRecognitionError("Модель не вернула структурированный ответ")

    # SDK отдаёт input уже разобранным в dict — строковый разбор не нужен.
    return _build_analysis(dict(tool_use.input))


async def analyze_photo(
    image_bytes: bytes,
    *,
    hint: str | None = None,
    media_type: str = "image/jpeg",
) -> FoodAnalysis:
    """Распознать блюдо по фото. `hint` — уточнение пользователя («это не борщ, а солянка»)."""
    encoded = base64.standard_b64encode(image_bytes).decode("utf-8")

    text = "Что это за блюдо и сколько в нём КБЖУ?"
    if hint:
        text = (
            f"Что это за блюдо и сколько в нём КБЖУ?\n"
            f"Пользователь уточнил, что на фото: {hint}. "
            f"Доверься уточнению в названии, а вес порции по-прежнему оцени по фото."
        )

    return await _analyze(
        [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": encoded},
            },
            {"type": "text", "text": text},
        ]
    )


async def analyze_text(description: str) -> FoodAnalysis:
    """Распознать блюдо по текстовому описанию («тарелка борща и два куска хлеба»)."""
    return await _analyze(
        [
            {
                "type": "text",
                "text": (
                    "Оцени КБЖУ по описанию пользователя. Если порция не указана — "
                    "считай её стандартной для этого блюда.\n\n"
                    f"Описание: {description}"
                ),
            }
        ]
    )
