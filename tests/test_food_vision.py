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
    VisionNotConfigured,
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
    "fiber_g": 6,
    "confidence": "medium",
    "comment": "оценил как порцию каши на молоке",
}


def test_build_analysis_maps_payload():
    analysis = _build_analysis(VALID_PAYLOAD)
    assert analysis.name == "Овсяная каша с бананом"
    assert analysis.weight_g == 250
    assert analysis.calories == 320
    assert analysis.confidence == "medium"


def test_build_analysis_reads_fiber():
    assert _build_analysis(VALID_PAYLOAD).fiber_g == 6


def test_build_analysis_defaults_fiber_to_zero_when_missing():
    """Модель обязана вернуть fiber_g, но нолём это не ломается."""
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "fiber_g"}
    assert _build_analysis(payload).fiber_g == 0.0


def test_analysis_from_old_fsm_data_without_fiber():
    """Карточки, сохранённые до появления клетчатки, ещё лежат в FSM."""
    old = {k: v for k, v in _build_analysis(VALID_PAYLOAD).to_dict().items() if k != "fiber_g"}
    assert FoodAnalysis.from_dict(old).fiber_g == 0.0


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


class _FakeClient:
    """Подменяет anthropic-клиент: ловит аргументы запроса и отдаёт ответ."""

    def __init__(self, response, captured: dict):
        outer = self

        class _Messages:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return outer._response

        self._response = response
        self.messages = _Messages()


def _mock_claude(monkeypatch, response, captured: dict):
    monkeypatch.setattr(food_vision, "_client", _FakeClient(response, captured))


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
    # Клетчатку модель обязана заполнять, а не «если получится».
    assert "fiber_g" in captured["tools"][0]["input_schema"]["required"]


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


def test_analysis_requires_api_key(monkeypatch):
    """Без ключа — понятная ошибка, а не падение бота."""
    monkeypatch.setattr(food_vision, "_client", None)
    monkeypatch.setattr(food_vision.config, "ANTHROPIC_API_KEY", "")

    with pytest.raises(VisionNotConfigured, match="ключ Anthropic не задан"):
        asyncio.run(food_vision.analyze_photo(IMAGE_BYTES))


class _RaisingClient:
    """Клиент, который падает заданной ошибкой anthropic."""

    def __init__(self, error):
        outer = self

        class _Messages:
            async def create(self, **kwargs):
                raise outer._error

        self._error = error
        self.messages = _Messages()


def _fake_api_error(cls, status_code, message):
    """Собрать исключение SDK, не делая настоящий HTTP-запрос."""
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request, json={"error": {"message": message}})
    return cls(message, response=response, body=None)


def test_invalid_key_reported_as_configuration_problem(monkeypatch):
    import anthropic

    error = _fake_api_error(anthropic.AuthenticationError, 401, "invalid x-api-key")
    monkeypatch.setattr(food_vision, "_client", _RaisingClient(error))

    with pytest.raises(VisionNotConfigured, match="Ключ Anthropic не принят"):
        asyncio.run(food_vision.analyze_photo(IMAGE_BYTES))


def test_empty_balance_reported_plainly(monkeypatch):
    import anthropic

    error = _fake_api_error(
        anthropic.BadRequestError, 400, "Your credit balance is too low to access the API"
    )
    monkeypatch.setattr(food_vision, "_client", _RaisingClient(error))

    with pytest.raises(FoodRecognitionError, match="закончились деньги"):
        asyncio.run(food_vision.analyze_photo(IMAGE_BYTES))


def test_rate_limit_reported_plainly(monkeypatch):
    import anthropic

    error = _fake_api_error(anthropic.RateLimitError, 429, "rate limit")
    monkeypatch.setattr(food_vision, "_client", _RaisingClient(error))

    with pytest.raises(FoodRecognitionError, match="Слишком много запросов"):
        asyncio.run(food_vision.analyze_photo(IMAGE_BYTES))
