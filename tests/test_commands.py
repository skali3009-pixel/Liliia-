"""Список команд в меню Telegram.

Главное здесь — не текст, а то, что каждая строка списка ведёт к живому
обработчику. Пункт меню, за которым ничего нет, — худший вид поломки:
человек нажимает, ничего не происходит, и жаловаться не на что.
"""

import re
from pathlib import Path

import pytest

import config
from services import commands

ROOT = Path(__file__).resolve().parent.parent


def registered() -> set[str]:
    """Все команды, которые бот действительно обрабатывает."""
    found: set[str] = set()
    for path in (ROOT / "handlers").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        found |= set(re.findall(r'Command\("([a-z_]+)"\)', source))
        if "CommandStart()" in source:
            found.add("start")
    return found


def test_every_command_in_the_menu_really_exists():
    """Пункт без обработчика молча ничего не делает."""
    listed = {name for name, _ in commands.PUBLIC + commands.PAID + commands.ADMIN}
    missing = listed - registered()
    assert not missing, f"в меню есть, а в боте нет: {sorted(missing)}"


def test_the_menu_is_short_enough_to_read():
    """Telegram показывает список всплывающим окном: двадцать строк — это ноль."""
    assert len(commands.public()) <= 10


def test_every_line_is_explained_in_russian():
    for name, text in commands.PUBLIC + commands.PAID + commands.ADMIN:
        assert text and text[0].isupper(), name
        # Telegram обрезает описания длиннее 256 символов, но читаются
        # только короткие.
        assert len(text) <= 60, name


def test_owner_commands_are_not_shown_to_everyone():
    """/grant в общем списке — приглашение его потыкать."""
    public = {name for name, _ in commands.public()}
    for private in ("grant", "admin", "report", "id"):
        assert private not in public, private
        assert private in {name for name, _ in commands.admin()}, private


def test_the_owner_sees_everything_others_see():
    assert set(commands.public()) <= set(commands.admin())


def test_the_subscription_line_follows_the_paywall(monkeypatch):
    """В бесплатной бете строка про подписку заставляет гадать, что купил."""
    monkeypatch.setattr(config, "PAYWALL", False)
    assert "subscription" not in {name for name, _ in commands.public()}

    monkeypatch.setattr(config, "PAYWALL", True)
    assert "subscription" in {name for name, _ in commands.public()}


def test_data_rights_are_reachable_without_being_told():
    """Выгрузка и удаление данных — то, о чём человек обязан узнать сам."""
    public = {name for name, _ in commands.public()}
    assert {"export", "delete", "legal"} <= public


def test_the_bot_writes_the_list_on_startup():
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert "bot_commands.apply(bot)" in source


class FakeBot:
    def __init__(self, failing: bool = False):
        self.calls: list[tuple[int, object]] = []
        self.failing = failing

    async def set_my_commands(self, commands_list, scope=None):
        if self.failing:
            raise RuntimeError("Telegram недоступен")
        self.calls.append((len(commands_list), scope))


def test_the_owner_gets_a_personal_list(monkeypatch):
    import asyncio

    monkeypatch.setattr(commands.config, "ADMIN_IDS", [246959020])
    bot = FakeBot()
    asyncio.run(commands.apply(bot))

    assert len(bot.calls) == 2
    common, personal = bot.calls
    assert personal[0] > common[0], "личный список должен быть длиннее общего"


def test_a_telegram_failure_does_not_break_the_start(monkeypatch):
    """Меню — украшение. Из-за него бот подниматься не обязан."""
    import asyncio

    monkeypatch.setattr(commands.config, "ADMIN_IDS", [1])
    asyncio.run(commands.apply(FakeBot(failing=True)))
