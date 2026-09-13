"""Оплата не должна включаться сама собой.

Раньше платный доступ включало само появление ADMIN_IDS. Значит, попытка
получать отчёты о сбоях заодно закрывала бота от людей, которые пришли,
когда он был бесплатным. Теперь это два независимых переключателя.
"""

import importlib
import os

import pytest

BASE = {
    "BOT_TOKEN": "test:token",
    "ANTHROPIC_API_KEY": "test",
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
}


def load(monkeypatch, **env):
    for key, value in {**BASE, **env}.items():
        monkeypatch.setenv(key, value)
    for key in ("ADMIN_IDS", "PAYWALL"):
        if key not in env:
            monkeypatch.delenv(key, raising=False)

    import config
    return importlib.reload(config)


@pytest.fixture(autouse=True)
def restore_config():
    """Модуль общий на весь прогон — возвращаем его в исходное состояние."""
    yield
    import config
    saved = dict(os.environ)
    importlib.reload(config)
    os.environ.clear()
    os.environ.update(saved)


def test_owner_alone_does_not_turn_on_payment(monkeypatch):
    config = load(monkeypatch, ADMIN_IDS="246959020")
    assert config.ADMIN_IDS == {246959020}
    assert config.PAYWALL is False


def test_payment_needs_an_explicit_line_in_env(monkeypatch):
    config = load(monkeypatch, ADMIN_IDS="246959020", PAYWALL="1")
    assert config.PAYWALL is True


def test_payment_never_turns_on_without_an_owner(monkeypatch):
    """Иначе владелец закроет бота от самого себя и не сможет его починить."""
    config = load(monkeypatch, PAYWALL="1")
    assert config.PAYWALL is False


@pytest.mark.parametrize("value", ["0", "off", "no", "false", ""])
def test_words_for_no_keep_the_bot_free(monkeypatch, value):
    config = load(monkeypatch, ADMIN_IDS="246959020", PAYWALL=value)
    assert config.PAYWALL is False
