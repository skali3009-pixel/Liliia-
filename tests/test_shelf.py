"""«Сфоткай полку»: модель называет продукты, считаем всё равно мы сами.

Главное, что здесь проверяется, — граница доверия. Из ответа модели в подбор
попадают только коды из нашего справочника: выдуманное, чужое и повторы
отсекаются до того, как из этого начнут собирать еду.
"""

import asyncio
import base64

import pytest

from seed.nutrition.cube_rules import GROUP_INDEX
from services import food_vision, shelf_vision
from services.food_vision import FoodRecognitionError, VisionNotConfigured
from services.shelf_vision import Shelf, _build_shelf, _prompt, _tool, vocabulary
from tests.test_food_vision import _FakeBlock, _FakeClient, _FakeResponse

NAMES = {
    "kefir": "Кефир 1%",
    "cottage_cheese": "Творог 5%",
    "banana": "Банан",
    "crispbread": "Хлебцы",
    "walnut": "Грецкий орех",
    # Из справочника, но Кубик им не пользуется: варить в машине нечего.
    "buckwheat": "Гречка",
}
KNOWN = vocabulary(NAMES)

IMAGE_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def _mock_claude(monkeypatch, response, captured: dict):
    # Клиент Claude один на оба сервиса — подменяем его там, где он живёт.
    monkeypatch.setattr(food_vision, "_client", _FakeClient(response, captured))


# --- Словарь распознавания -------------------------------------------------

def test_vocabulary_keeps_only_what_the_cube_can_use():
    """Узнавать гречку на полке незачем: набор без приборов из неё не собрать."""
    assert "buckwheat" not in KNOWN
    assert "kefir" in KNOWN and "banana" in KNOWN


def test_vocabulary_never_offers_a_code_the_cube_does_not_know():
    assert set(KNOWN) <= set(GROUP_INDEX)


def test_vocabulary_is_ordered_so_the_prompt_can_be_cached():
    """Список продуктов кэшируется — значит, он должен быть одинаковым каждый раз."""
    assert list(vocabulary(NAMES)) == sorted(KNOWN)
    assert list(vocabulary(dict(reversed(list(NAMES.items()))))) == list(KNOWN)


def test_prompt_carries_names_next_to_codes():
    text = _prompt(KNOWN)
    assert "kefir — Кефир 1%" in text
    assert "Гречка" not in text


def test_tool_allows_only_known_codes():
    schema = _tool(KNOWN)["input_schema"]
    assert schema["properties"]["found"]["items"]["enum"] == list(KNOWN)
    assert _tool(KNOWN)["strict"] is True


# --- Разбор ответа ---------------------------------------------------------

def test_build_shelf_reads_codes_and_others():
    shelf = _build_shelf({"found": ["kefir", "banana"], "other": ["авокадо"]}, KNOWN)
    assert shelf.codes == ("kefir", "banana")
    assert shelf.other == ("авокадо",)
    assert shelf


def test_build_shelf_drops_a_code_we_do_not_know():
    """Схема такого не должна пропускать, но набор собирается из этих кодов."""
    shelf = _build_shelf({"found": ["kefir", "avocado", "buckwheat"]}, KNOWN)
    assert shelf.codes == ("kefir",)


def test_build_shelf_drops_repeats():
    """Одна и та же пачка на полке — это один продукт, а не три."""
    shelf = _build_shelf({"found": ["kefir", "kefir", "banana", "kefir"]}, KNOWN)
    assert shelf.codes == ("kefir", "banana")


def test_build_shelf_survives_an_empty_answer():
    shelf = _build_shelf({}, KNOWN)
    assert shelf.codes == () and shelf.other == ()
    assert not shelf


def test_build_shelf_caps_the_lists():
    payload = {"found": sorted(KNOWN) * 10, "other": [f"еда {i}" for i in range(50)]}
    shelf = _build_shelf(payload, KNOWN)
    assert len(shelf.codes) <= shelf_vision.MAX_FOUND
    assert len(shelf.other) <= shelf_vision.MAX_OTHER


def test_build_shelf_trims_long_and_empty_names():
    shelf = _build_shelf({"other": ["  ", "а" * 200, "  сыр косичка "]}, KNOWN)
    assert shelf.other == ("а" * shelf_vision.MAX_OTHER_LEN, "сыр косичка")


# --- Запрос к модели -------------------------------------------------------

def test_recognize_sends_the_photo_and_the_cached_list(monkeypatch):
    captured: dict = {}
    _mock_claude(monkeypatch, _FakeResponse([
        _FakeBlock("tool_use", {"found": ["kefir", "banana"], "other": []})]), captured)

    shelf = asyncio.run(shelf_vision.recognize(IMAGE_BYTES, NAMES))

    assert shelf.codes == ("kefir", "banana")
    image_block, text_block = captured["messages"][0]["content"]
    assert base64.standard_b64decode(image_block["source"]["data"]) == IMAGE_BYTES
    assert text_block["type"] == "text"
    # Список продуктов длинный и не меняется — он должен читаться из кэша.
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "kefir — Кефир 1%" in captured["system"][0]["text"]
    assert captured["tools"][0]["name"] == "record_shelf"


def test_recognize_counts_the_money(monkeypatch):
    spent: list = []
    _mock_claude(monkeypatch, _FakeResponse([_FakeBlock("tool_use", {"found": []})]), {})

    asyncio.run(shelf_vision.recognize(IMAGE_BYTES, NAMES, on_usage=spent.append))

    assert len(spent) == 1


def test_recognize_raises_when_the_model_just_talks(monkeypatch):
    _mock_claude(monkeypatch, _FakeResponse([_FakeBlock("text")]), {})

    with pytest.raises(FoodRecognitionError):
        asyncio.run(shelf_vision.recognize(IMAGE_BYTES, NAMES))


def test_recognize_refuses_an_empty_catalogue(monkeypatch):
    with pytest.raises(FoodRecognitionError, match="Справочник"):
        asyncio.run(shelf_vision.recognize(IMAGE_BYTES, {"buckwheat": "Гречка"}))


def test_recognize_explains_a_missing_key(monkeypatch):
    """Без ключа — понятная фраза, а не ошибка сервера."""
    monkeypatch.setattr(food_vision, "_client", None)
    monkeypatch.setattr(food_vision.config, "ANTHROPIC_API_KEY", "")

    with pytest.raises(VisionNotConfigured):
        asyncio.run(shelf_vision.recognize(IMAGE_BYTES, NAMES))


# --- Стык с Кубиком --------------------------------------------------------

def test_every_recognizable_product_can_land_in_a_cube():
    """Распознали — значит, из этого можно собрать набор, а не только назвать."""
    from seed.nutrition.cube_rules import GROUPS

    usable = {code for codes in GROUPS.values() for code in codes}
    assert set(vocabulary({code: code for code in GROUP_INDEX})) <= usable
