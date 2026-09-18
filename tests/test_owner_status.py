"""Техническая сводка в чат — /status.

До неё узнать, что с ботом, можно было только из консоли сервера. Когда
консоль перестала открываться, стало неоткуда: единственный канал
диагностики оказался тем самым, который и сломался. Телефон есть всегда.
"""

import asyncio

import config
from handlers import access
from services import commands as bot_commands

OWNER = 777
STRANGER = 42


class FakeMessage:
    def __init__(self, user_id):
        self.from_user = type("U", (), {"id": user_id})()
        self.said: list[str] = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        return self


def run(coro):
    return asyncio.run(coro)


def test_the_owner_gets_the_report_in_the_chat(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    monkeypatch.setattr(access, "_sync_status",
                        lambda: "Версия: abc123\n\n🖼 Картинки: все на месте")

    message = FakeMessage(OWNER)
    run(access.owner_status(message))

    assert message.said, "владелец должен получить ответ"
    assert "🖼 Картинки" in "\n".join(message.said)


def test_for_everyone_else_the_command_does_not_exist(monkeypatch):
    """Не «нет доступа», а тишина: чужому знать о команде незачем."""
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    monkeypatch.setattr(access, "_sync_status",
                        lambda: "секретная сводка")

    message = FakeMessage(STRANGER)
    run(access.owner_status(message))

    assert message.said == []


def test_a_long_report_is_cut_into_pieces_telegram_accepts(monkeypatch):
    """Telegram молча отказывает в сообщении длиннее четырёх тысяч знаков.

    Сводка растёт: каждая новая проверка — ещё строки. Один раз она
    перевалит за предел, и вместо отчёта владелец получит ошибку.
    """
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    long_report = "\n".join(f"строка отчёта номер {i}" for i in range(400))
    monkeypatch.setattr(access, "_sync_status", lambda: long_report)

    message = FakeMessage(OWNER)
    run(access.owner_status(message))

    assert len(message.said) > 1, "длинный отчёт должен прийти частями"
    for part in message.said:
        assert len(part) <= 4096
    # И ни одной строки не потеряно по дороге.
    assert "\n".join(message.said).count("строка отчёта") == 400


def test_lines_are_not_torn_in_the_middle():
    """Резать по буквам значит разорвать число пополам."""
    text = "\n".join(["короткая", "x" * 100, "ещё"])
    parts = access._split(text, 60)

    assert all(line in text.split("\n") for part in parts
               for line in part.split("\n"))


def test_the_command_is_listed_for_the_owner():
    """Команда, о которой нельзя узнать изнутри бота, всё равно что нет."""
    assert any(name == "status" for name, _ in bot_commands.ADMIN)
    # И только владельцу: чужим она не показывается.
    assert not any(name == "status" for name, _ in bot_commands.PUBLIC)
