"""Тесты подбора блюд: что уходит в модель и что приходит обратно."""

import asyncio

import pytest

from models import DietTypeEnum, GenderEnum, GoalEnum, User
from services import suggestions as module
from services.suggestions import build_request, suggest_meals
from utils.macros import remaining

NORMS = {"calories": 1600, "protein_g": 120, "fat_g": 48, "carbs_g": 160, "fiber_g": 22}

PAYLOAD = {
    "meals": [
        {"name": "Творог с ягодами", "weight_g": 200, "calories": 210, "protein_g": 30,
         "fat_g": 5, "carbs_g": 12, "fiber_g": 3, "why": "закроет недобор белка"},
        {"name": "Омлет с овощами", "weight_g": 250, "calories": 280, "protein_g": 22,
         "fat_g": 18, "carbs_g": 8, "fiber_g": 4, "why": "быстро готовится"},
        {"name": "Куриная грудка с гречкой", "weight_g": 300, "calories": 420, "protein_g": 40,
         "fat_g": 9, "carbs_g": 45, "fiber_g": 7, "why": "полноценный ужин"},
    ]
}


def make_user(**kwargs) -> User:
    defaults = dict(
        id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165, current_weight_kg=62,
        goal=GoalEnum.LOSE_WEIGHT, diet_type=DietTypeEnum.REGULAR, timezone="Europe/Moscow",
    )
    return User(**{**defaults, **kwargs})


def test_request_mentions_remaining_macros_and_limits():
    user = make_user(allergies="орехи, лактоза", diet_type=DietTypeEnum.VEGAN)
    left = remaining({"calories": 900, "protein_g": 60, "fat_g": 30, "carbs_g": 90}, NORMS)

    text = build_request(user, left, NORMS)

    assert "700 ккал" in text                 # остаток калорий
    assert "белки 60" in text
    assert "орехи, лактоза" in text           # аллергии переданы
    assert "веганское" in text                # тип питания переведён на русский


def test_request_reports_fiber_left():
    user = make_user()
    left = remaining({"calories": 900, "protein_g": 60, "fat_g": 30, "carbs_g": 90,
                      "fiber_g": 8}, NORMS)
    assert "Клетчатки до дневной цели осталось 14 г" in build_request(user, left, NORMS)


def test_request_names_the_biggest_gap():
    user = make_user()
    left = remaining({"calories": 900, "protein_g": 100, "fat_g": 40, "carbs_g": 60}, NORMS)
    assert "не хватает углеводов" in build_request(user, left, NORMS)


def test_request_softens_when_norm_is_used_up():
    user = make_user()
    left = remaining({"calories": 1600, "protein_g": 120, "fat_g": 48, "carbs_g": 160}, NORMS)
    assert "Норма почти выбрана" in build_request(user, left, NORMS)


class _Block:
    def __init__(self, block_type, payload=None):
        self.type = block_type
        self.input = payload


class _Response:
    def __init__(self, content):
        self.content = content
        self.stop_reason = "tool_use"


class _Client:
    def __init__(self, response, captured):
        outer = self

        class _Messages:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return outer._response

        self._response = response
        self.messages = _Messages()


def test_suggestions_parsed_from_tool_call(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        module, "get_client", lambda: _Client(_Response([_Block("tool_use", PAYLOAD)]), captured)
    )

    user = make_user()
    left = remaining({"calories": 900, "protein_g": 60, "fat_g": 30, "carbs_g": 90}, NORMS)
    items = asyncio.run(suggest_meals(user, left, NORMS))

    assert len(items) == 3
    assert items[0].name == "Творог с ягодами"
    assert items[0].calories == 210
    assert items[0].why == "закроет недобор белка"
    assert captured["tools"][0]["name"] == "suggest_meals"
    assert captured["tools"][0]["strict"] is True


def test_missing_tool_call_raises(monkeypatch):
    monkeypatch.setattr(module, "get_client", lambda: _Client(_Response([_Block("text")]), {}))

    user = make_user()
    left = remaining({}, NORMS)
    with pytest.raises(module.FoodRecognitionError):
        asyncio.run(suggest_meals(user, left, NORMS))
