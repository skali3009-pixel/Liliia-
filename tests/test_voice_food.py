"""Голосовое → еда: расшифровка, разбор фразы и честный ответ о сбое.

Поломка 04.10: на любое голосовое бот отвечал «Не получилось распознать
блюдо». Речь при этом расшифровывалась — падало обращение к модели при
разборе фразы, а его отказы не переводились в понятную причину: ни
человеку, ни владелице, ни в журнале было не видно, кончились ли деньги,
не принят ключ или модель недоступна.
"""

import asyncio
import io
import logging
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import handlers.food as food
import services.moments as moments
from services.food_vision import FoodRecognitionError

PHRASE = "Тарелка борща со сметаной и два куска бородинского."


def api_error(cls, status, message):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request,
                              json={"error": {"message": message}})
    return cls(message, response=response, body={"error": {"message": message}})


def tool_reply(food_name="Борщ со сметаной и бородинский хлеб"):
    block = SimpleNamespace(type="tool_use", name="record_moment", input={
        "summary": "Обед", "food_name": food_name, "weight_g": 400,
        "calories": 420, "protein_g": 14, "fat_g": 18, "carbs_g": 48,
        "fiber_g": 6, "energy": 0, "focus": 0, "mood": "", "stress": "",
        "sleep_hours": 0, "comment": ""})
    return SimpleNamespace(content=[block], stop_reason="tool_use", usage=None)


def fake_client(monkeypatch, *, error=None, reply=None):
    async def create(**kwargs):
        if error is not None:
            raise error
        return reply or tool_reply()
    monkeypatch.setattr(moments, "get_client",
                        lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))


# --- Разбор фразы: отказ Anthropic называется словами -------------------------

@pytest.mark.parametrize("error,words", [
    (api_error(anthropic.BadRequestError, 400,
               "Your credit balance is too low to access the Anthropic API."),
     "закончились деньги"),
    (api_error(anthropic.AuthenticationError, 401, "invalid x-api-key"), "Ключ Anthropic"),
    (api_error(anthropic.NotFoundError, 404, "model: claude-sonnet-5"), r"ответил ошибкой \(404\)"),
    (api_error(anthropic.InternalServerError, 529, "Overloaded"), r"ответил ошибкой \(529\)"),
])
def test_a_refusal_of_the_model_is_named(monkeypatch, error, words):
    fake_client(monkeypatch, error=error)

    with pytest.raises(FoodRecognitionError, match=words):
        asyncio.run(moments.analyze_moment(PHRASE))


def test_the_real_reason_goes_to_the_log(monkeypatch, caplog):
    fake_client(monkeypatch, error=api_error(
        anthropic.BadRequestError, 400, "Your credit balance is too low"))

    with caplog.at_level(logging.WARNING), pytest.raises(FoodRecognitionError):
        asyncio.run(moments.analyze_moment(PHRASE))

    logged = caplog.text
    assert "BadRequestError" in logged and "400" in logged
    assert "credit balance is too low" in logged


def test_a_normal_answer_still_becomes_a_meal(monkeypatch):
    fake_client(monkeypatch)

    moment = asyncio.run(moments.analyze_moment(PHRASE))

    assert moment.food is not None and moment.food.calories == 420


# --- Обработчик голосового: что видит человек ---------------------------------

class Status:
    def __init__(self, log):
        self.log = log

    async def edit_text(self, text, **kwargs):
        self.log.append(text)

    async def delete(self):
        self.log.append("<убрано>")


class Voice:
    def __init__(self, log):
        self.log = log
        self.from_user = SimpleNamespace(id=1)
        self.chat = SimpleNamespace(id=1)
        self.voice = SimpleNamespace(file_id="F")

        async def download(file_id):
            return io.BytesIO(b"OggS")

        async def chat_action(*args, **kwargs):
            return None
        self.bot = SimpleNamespace(download=download, send_chat_action=chat_action)

    async def answer(self, text, **kwargs):
        self.log.append(text)
        return Status(self.log)


def send_voice(monkeypatch, *, spoken=PHRASE):
    log, cards = [], []

    async def transcribe(audio, **kwargs):
        return spoken

    async def onboarded(message):
        return SimpleNamespace(id=1)

    async def show_card(message, state, analysis, photo_file_id=None):
        cards.append(analysis)

    monkeypatch.setattr(food, "transcribe", transcribe)
    monkeypatch.setattr(food, "_ensure_onboarded", onboarded)
    monkeypatch.setattr(food, "_show_card", show_card)
    state = FSMContext(storage=MemoryStorage(),
                       key=StorageKey(bot_id=1, chat_id=1, user_id=1))
    asyncio.run(food.handle_food_voice(Voice(log), state))
    return log, cards


def test_voice_reaches_the_meal_card(monkeypatch):
    fake_client(monkeypatch)

    _, cards = send_voice(monkeypatch)

    assert cards and cards[0].calories == 420


def test_a_short_voice_with_one_product_counts(monkeypatch):
    fake_client(monkeypatch, reply=tool_reply("Банан"))

    _, cards = send_voice(monkeypatch, spoken="Банан.")

    assert cards and cards[0].name == "Банан"


def test_no_money_on_the_account_is_said_after_what_was_heard(monkeypatch):
    fake_client(monkeypatch, error=api_error(
        anthropic.BadRequestError, 400, "Your credit balance is too low"))

    log, cards = send_voice(monkeypatch)

    assert not cards
    assert log[-1].startswith(f"🎤 Услышал: {PHRASE}")
    assert "закончились деньги" in log[-1]
    assert food.GENERIC_ERROR not in log[-1]


def test_an_unexpected_failure_keeps_what_was_heard(monkeypatch):
    """«Расслышал, но не понял блюдо» — отдельно от «не расслышал»."""
    fake_client(monkeypatch, error=RuntimeError("что-то сломалось внутри"))

    log, _ = send_voice(monkeypatch)

    assert log[-1] == f"🎤 Услышал: {PHRASE}\n\n{food.VOICE_HEARD_NOT_PARSED}"
