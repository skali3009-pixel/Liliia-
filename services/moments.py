"""Свободная фраза → разобранный «момент»: еда и/или состояние.

«Позавтракала, выпила кофе и чувствую себя бодрее» — это сразу приём пищи и
отметка энергии. Разбирает Claude вызовом инструмента со строгой схемой, а
пользователь потом подтверждает или переписывает фразу: догадки показываем
явно, молча ничего не сохраняем.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import config
from services.food_vision import FoodAnalysis, FoodRecognitionError, get_client

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024

MOODS = ["", "спокойно", "бодро", "радостно", "устала", "тревожно", "грустно", "раздражённо"]
STRESS_LEVELS = ["", "низкий", "средний", "высокий"]

SYSTEM_PROMPT = (
    "Ты разбираешь короткую фразу человека о его дне на факты. Человек ведёт дневник "
    "питания и самочувствия и говорит обычным языком.\n"
    "\n"
    "Правила:\n"
    "- Записывай только то, что сказано или прямо следует из фразы. Не выдумывай.\n"
    "- Если упомянута еда или напиток — оцени КБЖУ и клетчатку всей порции. "
    "В carbs_g указывай усвояемые углеводы без клетчатки.\n"
    "- Если про еду не сказано — оставь food_name пустым, а числа нулями.\n"
    "- energy и focus — от 1 до 10, 0 означает «не сказано». «Бодрее», «прилив сил» — "
    "это 7-8; «никакая», «без сил» — 2-3.\n"
    "- mood и stress выбирай из списка; если про них ничего нет — пустая строка.\n"
    "- sleep_hours — только если человек сказал, сколько спал.\n"
    "- summary — очень короткое название момента на русском: «Завтрак», «Прогулка», "
    "«Усталость к вечеру».\n"
    "- comment — одна фраза о том, что ты предположила при оценке порции. Без вступлений.\n"
    "\n"
    "Всегда вызывай инструмент record_moment. Не отвечай обычным текстом."
)

MOMENT_TOOL: dict[str, Any] = {
    "name": "record_moment",
    "description": "Записать разобранные факты из фразы человека.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Короткое название момента"},
            "food_name": {
                "type": "string",
                "description": "Название еды/напитка на русском, пустая строка, если еды нет",
            },
            "weight_g": {"type": "number", "description": "Вес порции, г; 0, если еды нет"},
            "calories": {"type": "number"},
            "protein_g": {"type": "number"},
            "fat_g": {"type": "number"},
            "carbs_g": {"type": "number", "description": "Углеводы без клетчатки, г"},
            "fiber_g": {"type": "number"},
            "energy": {"type": "number", "description": "Энергия 1-10; 0 — не сказано"},
            "focus": {"type": "number", "description": "Собранность 1-10; 0 — не сказано"},
            "mood": {"type": "string", "enum": MOODS},
            "stress": {"type": "string", "enum": STRESS_LEVELS},
            "sleep_hours": {"type": "number", "description": "Часы сна; 0 — не сказано"},
            "comment": {"type": "string"},
        },
        "required": [
            "summary", "food_name", "weight_g", "calories", "protein_g", "fat_g",
            "carbs_g", "fiber_g", "energy", "focus", "mood", "stress", "sleep_hours",
            "comment",
        ],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class Moment:
    """Что удалось понять из фразы."""

    summary: str
    text: str
    comment: str = ""
    food: FoodAnalysis | None = None
    energy: int | None = None
    focus: int | None = None
    mood: str | None = None
    stress: str | None = None
    sleep_minutes: int | None = None
    # Время момента «ЧЧ:ММ» — его можно поправить перед сохранением.
    at: str = ""

    @property
    def has_state(self) -> bool:
        return any(
            value is not None
            for value in (self.energy, self.focus, self.mood, self.stress, self.sleep_minutes)
        )

    @property
    def is_empty(self) -> bool:
        return self.food is None and not self.has_state

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["food"] = self.food.to_dict() if self.food else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Moment":
        food = data.get("food")
        return cls(**{**data, "food": FoodAnalysis.from_dict(food) if food else None})


def _score(value: Any) -> int | None:
    """Оценка 1-10; ноль и мусор означают «человек про это не говорил»."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 10 else None


def _choice(value: Any, allowed: list[str]) -> str | None:
    text = str(value or "").strip().lower()
    return text if text in allowed and text else None


def _positive(value: Any) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_moment(payload: dict[str, Any], *, text: str, at: str = "") -> Moment:
    """Собрать момент из ответа модели."""
    food_name = str(payload.get("food_name") or "").strip()
    food = None
    if food_name:
        food = FoodAnalysis(
            name=food_name[:60],
            weight_g=_positive(payload.get("weight_g")),
            calories=_positive(payload.get("calories")),
            protein_g=_positive(payload.get("protein_g")),
            fat_g=_positive(payload.get("fat_g")),
            carbs_g=_positive(payload.get("carbs_g")),
            fiber_g=_positive(payload.get("fiber_g")),
            confidence="medium",
            comment=str(payload.get("comment") or "").strip(),
        )

    sleep_hours = _positive(payload.get("sleep_hours"))
    return Moment(
        at=at or "",
        summary=str(payload.get("summary") or "Момент").strip()[:60],
        text=text.strip()[:500],
        comment=str(payload.get("comment") or "").strip()[:200],
        food=food,
        energy=_score(payload.get("energy")),
        focus=_score(payload.get("focus")),
        mood=_choice(payload.get("mood"), MOODS),
        stress=_choice(payload.get("stress"), STRESS_LEVELS),
        sleep_minutes=round(sleep_hours * 60) if 0 < sleep_hours <= 16 else None,
    )


async def analyze_moment(text: str, *, now: datetime | None = None) -> Moment:
    """Разобрать фразу человека на факты."""
    if not text.strip():
        raise FoodRecognitionError("Пустая фраза — расскажи, что происходит.")

    moment_time = (now or datetime.now()).strftime("%H:%M")
    response = await get_client().messages.create(
        model=config.VISION_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[MOMENT_TOOL],
        tool_choice={"type": "auto"},
        messages=[
            {
                "role": "user",
                "content": f"Сейчас {moment_time}. Фраза человека: {text.strip()}",
            }
        ],
    )

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        logger.warning("Модель не вызвала инструмент, stop_reason=%s", response.stop_reason)
        raise FoodRecognitionError("Не получилось разобрать фразу. Попробуй сказать иначе.")

    return build_moment(dict(tool_use.input), text=text, at=moment_time)


# Порядок фактов в карточке: сначала что съела, потом как себя чувствуешь,
# и в конце время. Каждый факт можно поправить — поэтому у него есть ключ
# и тип поля, а не только текст.
def facts(moment: Moment) -> list[dict[str, Any]]:
    """Распознанные факты для карточки подтверждения."""
    rows: list[dict[str, Any]] = []
    if moment.food:
        rows.append({"key": "food_name", "icon": "🍽️", "label": "Событие",
                     "value": moment.food.name, "type": "text", "raw": moment.food.name})
        rows.append({"key": "weight_g", "icon": "⚖️", "label": "Порция",
                     "value": f"{round(moment.food.weight_g)} г", "type": "number",
                     "raw": round(moment.food.weight_g)})
        rows.append({"key": "calories", "icon": "🔥", "label": "Калории",
                     "value": f"{round(moment.food.calories)} ккал", "type": "readonly"})
        rows.append({"key": "macros", "icon": "🥩", "label": "Б / Ж / У",
                     "value": (f"{round(moment.food.protein_g)} / {round(moment.food.fat_g)} / "
                               f"{round(moment.food.carbs_g)} г"), "type": "readonly"})
        if moment.food.fiber_g:
            rows.append({"key": "fiber_g", "icon": "🥦", "label": "Клетчатка",
                         "value": f"{round(moment.food.fiber_g)} г", "type": "readonly"})
    if moment.energy:
        rows.append({"key": "energy", "icon": "⚡", "label": "Энергия",
                     "value": f"{moment.energy} из 10", "type": "score", "raw": moment.energy})
    if moment.focus:
        rows.append({"key": "focus", "icon": "🎯", "label": "Фокус",
                     "value": f"{moment.focus} из 10", "type": "score", "raw": moment.focus})
    if moment.mood:
        rows.append({"key": "mood", "icon": "🤍", "label": "Настроение", "value": moment.mood,
                     "type": "choice", "options": [m for m in MOODS if m], "raw": moment.mood})
    if moment.stress:
        rows.append({"key": "stress", "icon": "〰️", "label": "Стресс", "value": moment.stress,
                     "type": "choice", "options": [s for s in STRESS_LEVELS if s],
                     "raw": moment.stress})
    if moment.sleep_minutes:
        hours, minutes = divmod(moment.sleep_minutes, 60)
        rows.append({"key": "sleep_minutes", "icon": "🌙", "label": "Сон",
                     "value": f"{hours} ч {minutes:02d} мин", "type": "readonly"})
    if moment.at:
        rows.append({"key": "at", "icon": "🕐", "label": "Время", "value": moment.at,
                     "type": "time", "raw": moment.at})
    return rows


__all__ = ["Moment", "analyze_moment", "build_moment", "facts", "MOMENT_TOOL"]
