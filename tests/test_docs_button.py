"""Кнопка «📄 Документы» в главном меню.

Документы показываются один раз, при согласии, а дальше жили только за
командой `/legal` в синем списке Telegram, куда не смотрит никто. Лилия:
«появляются один раз в начале, и всё, потом их не посмотреть».
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message as TgMessage, User

import config
from handlers import legal
from keyboards.main_menu import MENU_DOCS, MENU_TEXTS, main_menu_keyboard
from states.onboarding import OnboardingStates
from states.steps import StepStates


class Message:
    def __init__(self, text=MENU_DOCS):
        self.text = text
        self.from_user = SimpleNamespace(id=1)
        self.chat = SimpleNamespace(id=1)
        self.photo = self.voice = self.caption = None
        self.content_type = "text"
        self.said = []

    async def answer(self, text, **kwargs):
        self.said.append((text, kwargs.get("reply_markup")))


def press(state_before=None):
    """Настоящая доставка нажатия через роутер документов."""
    async def run():
        state = FSMContext(storage=MemoryStorage(),
                           key=StorageKey(bot_id=1, chat_id=1, user_id=1))
        if state_before:
            await state.set_state(state_before)
        message = Message()
        await legal.router.propagate_event(
            update_type="message", event=message, state=state,
            raw_state=await state.get_state(), event_from_user=message.from_user,
            bot=SimpleNamespace(id=1, username="bot"))
        return message, await state.get_state()
    return asyncio.run(run())


def links(markup):
    return [button.url for row in markup.inline_keyboard for button in row]


def test_the_button_is_in_the_menu_and_counts_as_a_menu_press():
    labels = [b.text for row in main_menu_keyboard().keyboard for b in row]
    assert MENU_DOCS in labels
    # Без этого человек, начавший вводить шаги, нажал бы «Документы», а
    # сценарий съел бы нажатие как ответ.
    assert MENU_DOCS in MENU_TEXTS


def test_pressing_it_shows_all_four_documents(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.test")
    message, _ = press()
    assert message.said, "кнопка никому не дошла"
    text, markup = message.said[-1]
    assert "Документы сервиса" in text
    urls = links(markup)
    for slug in ("offer", "privacy", "consent", "marketing"):
        assert f"https://example.test/legal/{slug}" in urls, slug


def test_pressing_it_releases_an_unfinished_answer(monkeypatch):
    """Иначе следующая фраза уехала бы в поле шагов."""
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.test")
    message, left = press(StepStates.waiting_number)
    assert message.said
    assert left is None


def test_pressing_it_keeps_the_questionnaire(monkeypatch):
    """Ответы анкеты дороже: документы ничего не спрашивают."""
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.test")
    message, left = press(OnboardingStates.age)
    assert message.said
    assert left == OnboardingStates.age.state


def test_documents_open_without_paid_access_and_for_minors():
    """Закон не спрашивает, оплачена ли подписка и сколько человеку лет."""
    from middlewares.access import _is_open as paid_open
    from middlewares.minor import _is_open as minor_open

    message = TgMessage(message_id=1, date=datetime.now(),
                        chat=Chat(id=1, type="private"),
                        from_user=User(id=1, is_bot=False, first_name="x"),
                        text=MENU_DOCS)
    assert paid_open(message)
    assert minor_open(message, None)
