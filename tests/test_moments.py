"""Тесты разбора свободной фразы на факты (services/moments.py)."""

import asyncio

import pytest

from services import moments as module
from services.food_vision import FoodRecognitionError
from services.moments import Moment, analyze_moment, build_moment, facts

FOOD_AND_STATE = {
    "summary": "Завтрак",
    "food_name": "Овсянка с бананом и кофе",
    "weight_g": 300,
    "calories": 360,
    "protein_g": 10,
    "fat_g": 8,
    "carbs_g": 55,
    "fiber_g": 6,
    "energy": 7,
    "focus": 0,
    "mood": "бодро",
    "stress": "",
    "sleep_hours": 0,
    "comment": "оценила как порцию каши на молоке",
}


def test_food_and_state_are_parsed_together():
    moment = build_moment(FOOD_AND_STATE, text="Позавтракала и чувствую себя бодрее")
    assert moment.food.name == "Овсянка с бананом и кофе"
    assert moment.food.fiber_g == 6
    assert moment.energy == 7
    assert moment.mood == "бодро"
    assert moment.has_state


def test_zero_means_not_mentioned():
    """Ноль в ответе модели — это «человек про это не говорил», а не оценка 0."""
    moment = build_moment(FOOD_AND_STATE, text="…")
    assert moment.focus is None
    assert moment.stress is None
    assert moment.sleep_minutes is None


def test_state_without_food():
    payload = {**FOOD_AND_STATE, "food_name": "", "weight_g": 0, "calories": 0,
               "protein_g": 0, "fat_g": 0, "carbs_g": 0, "fiber_g": 0}
    moment = build_moment(payload, text="Устала к вечеру")
    assert moment.food is None
    assert moment.has_state
    assert not moment.is_empty


def test_empty_moment_is_detected():
    payload = {**FOOD_AND_STATE, "food_name": "", "energy": 0, "mood": "", "stress": "",
               "sleep_hours": 0, "focus": 0}
    assert build_moment(payload, text="просто так").is_empty


def test_sleep_is_converted_to_minutes():
    moment = build_moment({**FOOD_AND_STATE, "sleep_hours": 7.5}, text="Спала семь с половиной")
    assert moment.sleep_minutes == 450


def test_absurd_sleep_is_ignored():
    assert build_moment({**FOOD_AND_STATE, "sleep_hours": 40}, text="…").sleep_minutes is None


def test_unknown_mood_is_dropped():
    """Модель обязана выбирать из списка, но мусор не должен попадать в базу."""
    assert build_moment({**FOOD_AND_STATE, "mood": "пятница"}, text="…").mood is None


def test_moment_survives_roundtrip_through_json():
    moment = build_moment(FOOD_AND_STATE, text="Позавтракала")
    assert Moment.from_dict(moment.to_dict()) == moment


def test_facts_list_food_then_state():
    rows = facts(build_moment(FOOD_AND_STATE, text="…"))
    labels = [row["label"] for row in rows]
    assert labels[:3] == ["Еда", "Порция", "БЖУ"]
    assert "Энергия" in labels and "Настроение" in labels


class _Block:
    def __init__(self, block_type, payload=None):
        self.type = block_type
        self.input = payload


class _Response:
    def __init__(self, content):
        self.content = content
        self.stop_reason = "tool_use"


class _FakeClient:
    def __init__(self, response, captured):
        outer = self

        class _Messages:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return outer._response

        self._response = response
        self.messages = _Messages()


def test_request_uses_strict_tool_and_passes_the_phrase(monkeypatch):
    captured = {}
    monkeypatch.setattr(module, "get_client",
                        lambda: _FakeClient(_Response([_Block("tool_use", FOOD_AND_STATE)]), captured))

    moment = asyncio.run(analyze_moment("Позавтракала, выпила кофе"))

    assert moment.summary == "Завтрак"
    assert captured["tools"][0]["name"] == "record_moment"
    assert captured["tools"][0]["strict"] is True
    assert "Позавтракала, выпила кофе" in captured["messages"][0]["content"]


def test_empty_phrase_is_rejected_without_calling_the_model():
    with pytest.raises(FoodRecognitionError):
        asyncio.run(analyze_moment("   "))


def test_missing_tool_call_is_reported(monkeypatch):
    monkeypatch.setattr(module, "get_client",
                        lambda: _FakeClient(_Response([_Block("text")]), {}))
    with pytest.raises(FoodRecognitionError):
        asyncio.run(analyze_moment("что-то"))
