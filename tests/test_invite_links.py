"""Ссылки-приглашения: от имени бота зависят и друзья, и команда.

Поломка тихая и полная: бот работает, экраны открываются, а кнопка «Позвать»
отвечает «ссылка появится, когда у бота будет имя». Позвать кого-нибудь
становится нельзя вообще, и понять, что именно сломалось, человеку неоткуда.
"""

import asyncio

import pytest

import config


class FakeMe:
    def __init__(self, username):
        self.username = username


class FakeBot:
    def __init__(self, username="aura_bot", failing=False):
        self.me = FakeMe(username)
        self.failing = failing

    async def get_me(self):
        if self.failing:
            raise RuntimeError("Telegram недоступен")
        return self.me


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(config, "BOT_USERNAME", "")
    yield


def _learn(monkeypatch, bot) -> str:
    from services import identity

    monkeypatch.setattr(identity.config, "BOT_USERNAME", config.BOT_USERNAME)
    return asyncio.run(identity.learn_username(bot))


def test_the_bot_asks_telegram_for_its_own_name(monkeypatch):
    """Требовать имя от человека незачем: бот и так знает его о себе."""
    assert _learn(monkeypatch, FakeBot("@aura_bot")) == "aura_bot"


def test_a_name_set_by_hand_is_not_overwritten(monkeypatch):
    from services import identity

    monkeypatch.setattr(identity.config, "BOT_USERNAME", "своё_имя")
    assert asyncio.run(identity.learn_username(FakeBot("другое"))) == "своё_имя"


def test_telegram_being_down_does_not_stop_the_start(monkeypatch):
    assert _learn(monkeypatch, FakeBot(failing=True)) == ""


def test_the_start_really_asks_for_the_name():
    """Иначе сервис есть, а зовёт его никто."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    assert "identity.learn_username(bot)" in source


def test_the_status_report_says_when_invites_are_broken(monkeypatch):
    from services import status

    monkeypatch.setattr(status.config, "BOT_USERNAME", "")
    broken = "\n".join(status._invite_lines())
    assert "НЕ РАБОТАЮТ" in broken and "Позвать" in broken

    monkeypatch.setattr(status.config, "BOT_USERNAME", "aura_bot")
    fine = "\n".join(status._invite_lines())
    assert "работают" in fine and "aura_bot" in fine


def test_both_invite_links_depend_on_the_same_name():
    """Друзья и команда ломаются вместе — значит, чинить надо одно место."""
    from pathlib import Path

    api = (Path(__file__).resolve().parent.parent / "webapp" /
           "api.py").read_text(encoding="utf-8")
    assert api.count("config.BOT_USERNAME") >= 3
    assert "start=friend_" in api and "start=team_" in api
