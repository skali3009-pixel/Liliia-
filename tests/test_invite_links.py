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


def test_both_invite_links_depend_on_the_same_name(monkeypatch):
    """Друзья и команда ломаются вместе — значит, чинить надо одно место.

    Раньше это проверялось подсчётом слова BOT_USERNAME в файле приложения:
    обе ссылки собирались там руками. Теперь их собирает одна функция, и
    гарантия переехала за ними — она сильнее прежней, потому что проверяет
    не «сколько раз упомянуто», а что вторая ссылка правда идёт через ту же
    дверь.
    """
    from services import friends, identity, teams

    monkeypatch.setattr(identity.config, "BOT_USERNAME", "aura_bot")
    assert friends.invite_link("КОД") == "https://t.me/aura_bot?start=friend_КОД"
    assert teams.invite_link("КОД") == "https://t.me/aura_bot?start=team_КОД"

    # Имя пропало — молчат обе, а не одна.
    monkeypatch.setattr(identity.config, "BOT_USERNAME", "")
    assert friends.invite_link("КОД") == ""
    assert teams.invite_link("КОД") == ""


def test_nobody_builds_an_invite_link_by_hand():
    """Вторая такая строка где-нибудь ещё — это вторая ссылка, которую забудут починить."""
    from pathlib import Path

    корень = Path(__file__).resolve().parent.parent
    свои = {корень / "services" / "identity.py"}

    виноватые = []
    for файл in корень.rglob("*.py"):
        if файл in свои or "/tests/" in str(файл) or "/promo/" in str(файл):
            continue
        # Ищем именно сборку адреса, а не слова о ней: объяснять в
        # комментарии, как выглядит ссылка, никому не запрещено.
        if "https://t.me/" in файл.read_text(encoding="utf-8"):
            виноватые.append(str(файл.relative_to(корень)))

    assert not виноватые, f"ссылка собирается мимо identity.start_link: {виноватые}"


def test_the_invite_prefix_is_written_once():
    """Приставку меняют в одном месте, иначе выпуск и приём разъедутся молча."""
    from pathlib import Path

    корень = Path(__file__).resolve().parent.parent
    хозяева = {"services/friends.py": '"friend_"', "services/teams.py": '"team_"'}

    for файл in корень.rglob("*.py"):
        имя = str(файл.relative_to(корень))
        if имя.startswith(("tests/", "promo/")):
            continue
        текст = файл.read_text(encoding="utf-8")
        for хозяин, приставка in хозяева.items():
            if имя == хозяин:
                assert текст.count(приставка) == 1, имя
            else:
                assert приставка not in текст, f"{имя} держит свою копию {приставка}"
