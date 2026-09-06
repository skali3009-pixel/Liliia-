"""«Что-то не так»: голос человека доходит до владельца, а ответ — обратно.

Падения бот ловит сам. Но самое частое — не падение: «пришёл какой-то отчёт,
что это?», «непонятно, куда нажимать». В логах такое выглядит безупречно.

Проверяется в основном не текст, а две вещи: что ответ владельца доходит
обратно (без этого получается ящик для жалоб) и что кнопкой нельзя завалить
чат владельца.
"""

import asyncio

import pytest
from aiogram.dispatcher.event.bases import SkipHandler

import config
from handlers import feedback as handler
from services import feedback

OWNER = 246959020
PERSON = 707


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    feedback.reset()
    monkeypatch.setattr(config, "ADMIN_IDS", [OWNER])
    monkeypatch.setattr(feedback.config, "ADMIN_IDS", [OWNER])
    monkeypatch.setattr(handler.config, "ADMIN_IDS", [OWNER])
    yield
    feedback.reset()


class FakeBot:
    def __init__(self, failing_for: set[int] | None = None):
        self.sent: list[tuple[int, str]] = []
        self.markups: list = []
        self.failing_for = failing_for or set()

    async def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.failing_for:
            raise RuntimeError("заблокировал бота")
        self.sent.append((chat_id, text))
        self.markups.append(kwargs.get("reply_markup"))


class FakeState:
    def __init__(self, state=None, data=None):
        self.state = state
        self.data = dict(data or {})
        self.cleared = False

    async def set_state(self, value):
        self.state = value

    async def get_data(self):
        return self.data

    async def update_data(self, **values):
        self.data.update(values)

    async def clear(self):
        self.state, self.data, self.cleared = None, {}, True


class FakeMessage:
    def __init__(self, text="", user_id=PERSON, name="Лилия"):
        self.text = text
        self.from_user = type("U", (), {"id": user_id, "full_name": name})()
        self.said: list[str] = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        return self


class FakeCallback:
    def __init__(self, data, user_id=PERSON):
        self.data = data
        self.from_user = type("U", (), {"id": user_id, "full_name": "Лилия"})()
        self.message = FakeMessage(user_id=user_id)
        self.answers: list[str] = []

    async def answer(self, text="", **kwargs):
        self.answers.append(text)


def run(scenario):
    asyncio.run(scenario())


# --- Туда ------------------------------------------------------------------

def test_the_story_reaches_the_owner_with_who_and_from_where():
    async def scenario():
        bot, message, state = FakeBot(), FakeMessage("пришёл какой-то отчёт"), FakeState()
        await handler.take_report(message, state, bot)

        (chat_id, text), = bot.sent
        assert chat_id == OWNER
        assert "пришёл какой-то отчёт" in text
        assert str(PERSON) in text and "Лилия" in text
        assert "чат" in text
        assert "Спасибо" in message.said[0]
    run(scenario)


def test_the_owner_gets_a_way_to_answer():
    """Без кнопки это ящик для жалоб: у человека может не быть имени в Telegram."""
    async def scenario():
        bot = FakeBot()
        await handler.take_report(FakeMessage("непонятно"), FakeState(), bot)

        markup, = bot.markups
        assert markup is not None
        button, = [b for row in markup.inline_keyboard for b in row]
        assert str(PERSON) in button.callback_data
    run(scenario)


def test_an_empty_story_is_not_passed_on():
    async def scenario():
        bot, message = FakeBot(), FakeMessage("   ")
        await handler.take_report(message, FakeState(), bot)
        assert bot.sent == []
        assert "словами" in message.said[0]
    run(scenario)


def test_a_very_long_story_is_trimmed_before_the_chat():
    assert len(feedback.clean("я" * 5000)) == feedback.MAX_TEXT


def test_one_person_cannot_flood_the_owner():
    async def scenario():
        bot = FakeBot()
        for _ in range(10):
            await handler.take_report(FakeMessage("опять"), FakeState(), bot)
        assert len(bot.sent) == feedback.PER_HOUR
    run(scenario)


def test_a_limited_person_is_told_why_and_not_ignored():
    async def scenario():
        bot = FakeBot()
        for _ in range(feedback.PER_HOUR):
            await handler.take_report(FakeMessage("раз"), FakeState(), bot)

        message = FakeMessage("ещё раз")
        await handler.take_report(message, FakeState(), bot)
        assert "попозже" in message.said[0]
    run(scenario)


def test_the_limit_is_personal_not_shared():
    """Один болтливый человек не должен закрывать дорогу остальным."""
    async def scenario():
        bot = FakeBot()
        for _ in range(feedback.PER_HOUR + 2):
            await handler.take_report(FakeMessage("я", user_id=1), FakeState(), bot)

        message = FakeMessage("а у меня своё", user_id=2)
        await handler.take_report(message, FakeState(), bot)
        assert "Спасибо" in message.said[0]
    run(scenario)


def test_nothing_is_lost_silently_when_there_is_no_owner(monkeypatch):
    async def scenario():
        monkeypatch.setattr(handler.config, "ADMIN_IDS", [])
        message = FakeMessage("важное")
        await handler.take_report(message, FakeState(), FakeBot())
        assert "позже" in message.said[0]
    run(scenario)


def test_a_menu_button_ends_the_story_instead_of_sending_it():
    """Иначе человек, ушедший в «Воду», отправит владельцу слово «Вода»."""
    async def scenario():
        from keyboards.main_menu import MENU_WATER

        state = FakeState(state="writing")
        with pytest.raises(SkipHandler):
            await handler.leave_writing(FakeMessage(MENU_WATER), state)
        assert state.cleared
    run(scenario)


# --- Обратно ---------------------------------------------------------------

def test_the_owner_can_answer_and_the_person_gets_it():
    async def scenario():
        bot = FakeBot()
        callback = FakeCallback(f"{handler.CB_ANSWER}{PERSON}", user_id=OWNER)
        state = FakeState()

        await handler.start_answer(callback, state)
        assert state.data["answer_to"] == PERSON

        owner_message = FakeMessage("это итоги недели, их можно выключить",
                                    user_id=OWNER)
        await handler.send_answer(owner_message, state, bot)

        (chat_id, text), = bot.sent
        assert chat_id == PERSON
        assert "итоги недели" in text
        # Подписано: иначе выглядит как рассылка непонятно от кого.
        assert feedback.ANSWER_PREFIX in text
        assert "Отправила" in owner_message.said[0]
    run(scenario)


def test_a_stranger_cannot_press_the_answer_button():
    async def scenario():
        callback = FakeCallback(f"{handler.CB_ANSWER}{PERSON}", user_id=12345)
        state = FakeState()
        await handler.start_answer(callback, state)

        assert state.state is None
        assert "не твоя" in callback.answers[0]
    run(scenario)


def test_a_broken_answer_button_does_not_crash():
    async def scenario():
        callback = FakeCallback(f"{handler.CB_ANSWER}не-число", user_id=OWNER)
        state = FakeState()
        await handler.start_answer(callback, state)
        assert state.state is None
    run(scenario)


def test_the_owner_is_told_when_the_answer_did_not_reach():
    async def scenario():
        bot = FakeBot(failing_for={PERSON})
        state = FakeState(data={"answer_to": PERSON})
        owner_message = FakeMessage("ответ", user_id=OWNER)

        await handler.send_answer(owner_message, state, bot)
        assert "заблокировать" in owner_message.said[0]
    run(scenario)


def test_the_button_lives_where_people_look_for_it():
    from keyboards.profile import CB_PROBLEM, edit_menu_keyboard

    buttons = [b for row in edit_menu_keyboard().inline_keyboard for b in row]
    assert any(b.callback_data == CB_PROBLEM for b in buttons)
    # Последней: её ищут, когда всё остальное уже не помогло.
    assert buttons[-1].callback_data == CB_PROBLEM
