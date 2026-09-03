"""Тесты запроса к Claude vision, разбора ответа и выбора типа приёма пищи."""

import asyncio
import base64
from datetime import datetime

import pytest

from models import MealTypeEnum
from services import food_vision
from services.food_vision import (
    FoodAnalysis,
    FoodNotRecognized,
    FoodRecognitionError,
    _build_analysis,
)
from utils.meal_time import guess_meal_type

VALID_PAYLOAD = {
    "recognized": True,
    "name": "Овсяная каша с бананом",
    "weight_g": 250,
    "calories": 320,
    "protein_g": 9,
    "fat_g": 7,
    "carbs_g": 55,
    "confidence": "medium",
    "comment": "оценил как порцию каши на молоке",
}


def test_build_analysis_maps_payload():
    analysis = _build_analysis(VALID_PAYLOAD)
    assert analysis.name == "Овсяная каша с бананом"
    assert analysis.weight_g == 250
    assert analysis.calories == 320
    assert analysis.confidence == "medium"


def test_build_analysis_raises_when_no_food_recognized():
    payload = {**VALID_PAYLOAD, "recognized": False, "comment": "На фото не еда, а кот"}
    with pytest.raises(FoodNotRecognized, match="кот"):
        _build_analysis(payload)


def test_build_analysis_requires_name():
    with pytest.raises(FoodRecognitionError):
        _build_analysis({**VALID_PAYLOAD, "name": "   "})


def test_build_analysis_clamps_negative_and_invalid_numbers():
    analysis = _build_analysis({**VALID_PAYLOAD, "calories": -100, "fat_g": "нет данных"})
    assert analysis.calories == 0.0
    assert analysis.fat_g == 0.0


def test_build_analysis_truncates_long_name():
    analysis = _build_analysis({**VALID_PAYLOAD, "name": "блюдо " * 40})
    assert len(analysis.name) <= 60


def test_analysis_survives_fsm_roundtrip():
    analysis = _build_analysis(VALID_PAYLOAD)
    assert FoodAnalysis.from_dict(analysis.to_dict()) == analysis


class _FakeBlock:
    def __init__(self, block_type: str, payload=None):
        self.type = block_type
        self.input = payload


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.stop_reason = "tool_use"


def _mock_claude(monkeypatch, response, captured: dict):
    async def fake_create(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(food_vision._client.messages, "create", fake_create)


IMAGE_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_analyze_photo_sends_image_and_tool(monkeypatch):
    captured: dict = {}
    _mock_claude(monkeypatch, _FakeResponse([_FakeBlock("tool_use", VALID_PAYLOAD)]), captured)

    analysis = asyncio.run(food_vision.analyze_photo(IMAGE_BYTES))

    assert analysis.name == "Овсяная каша с бананом"

    image_block, text_block = captured["messages"][0]["content"]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert base64.standard_b64decode(image_block["source"]["data"]) == IMAGE_BYTES
    assert text_block["type"] == "text"

    # Структурированный ответ обеспечивается strict-инструментом.
    assert captured["tools"][0]["name"] == "record_food_analysis"
    assert captured["tools"][0]["strict"] is True


def test_analyze_photo_passes_user_hint_into_prompt(monkeypatch):
    captured: dict = {}
    _mock_claude(monkeypatch, _FakeResponse([_FakeBlock("tool_use", VALID_PAYLOAD)]), captured)

    asyncio.run(food_vision.analyze_photo(IMAGE_BYTES, hint="это солянка"))

    text_block = captured["messages"][0]["content"][1]
    assert "это солянка" in text_block["text"]


def test_analyze_text_sends_only_text(monkeypatch):
    captured: dict = {}
    _mock_claude(monkeypatch, _FakeResponse([_FakeBlock("tool_use", VALID_PAYLOAD)]), captured)

    asyncio.run(food_vision.analyze_text("омлет из трёх яиц"))

    content = captured["messages"][0]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert "омлет из трёх яиц" in content[0]["text"]


def test_analyze_raises_when_model_returns_no_tool_call(monkeypatch):
    _mock_claude(monkeypatch, _FakeResponse([_FakeBlock("text")]), {})

    with pytest.raises(FoodRecognitionError):
        asyncio.run(food_vision.analyze_photo(IMAGE_BYTES))


@pytest.mark.parametrize(
    "hour,expected",
    [
        (8, MealTypeEnum.BREAKFAST),
        (13, MealTypeEnum.LUNCH),
        (19, MealTypeEnum.DINNER),
        (23, MealTypeEnum.SNACK),
        (3, MealTypeEnum.SNACK),
    ],
)
def test_guess_meal_type_by_hour(hour, expected):
    assert guess_meal_type(datetime(2026, 1, 1, hour, 0)) == expected
