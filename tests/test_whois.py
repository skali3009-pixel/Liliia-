"""`/whois ID` — быстрый поиск покупателя по номеру в Telegram."""

import asyncio
import contextlib
from types import SimpleNamespace

import config
from handlers import access

OWNER = 777
STRANGER = 42
BUYER = 1089125542


class FakeMessage:
    def __init__(self, user_id: int, text: str):
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.said: list[str] = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        return self


class FakeSession:
    def __init__(self, user):
        self.user = user

    async def get(self, model, user_id):
        return self.user


def _patch(monkeypatch, *, allowed=True):
    user = SimpleNamespace(
        username="buyer", full_name="Покупатель Тестовый",
        first_source="direct_unknown", onboarding_completed=True,
    )

    @contextlib.asynccontextmanager
    async def get_session():
        yield FakeSession(user)

    async def check_access(session, user_id):
        return SimpleNamespace(allowed=allowed)

    monkeypatch.setattr(access, "get_session", get_session)
    monkeypatch.setattr(access, "check_access", check_access)


def test_only_the_owner_can_look_people_up(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    _patch(monkeypatch)
    message = FakeMessage(STRANGER, f"/whois {BUYER}")

    asyncio.run(access.whois(message))

    assert message.said == []


def test_whois_shows_name_telegram_and_access(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    _patch(monkeypatch)
    message = FakeMessage(OWNER, f"/whois {BUYER}")

    asyncio.run(access.whois(message))

    text = message.said[-1]
    assert str(BUYER) in text
    assert "Покупатель Тестовый" in text
    assert "@buyer" in text
    assert "Доступ: открыт" in text


def test_whois_explains_the_format(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    _patch(monkeypatch)
    message = FakeMessage(OWNER, "/whois")

    asyncio.run(access.whois(message))

    assert "Формат: /whois ID" in message.said[-1]
