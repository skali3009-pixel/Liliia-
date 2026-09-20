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


def _подменить_сводку(monkeypatch, текст):
    """Подменить сборку сводки, не трогая сам обработчик.

    Раньше тесты подменяли `access._sync_status` — обёртку, которая
    собирала сводку в отдельном потоке со своим циклом событий. Обёртки
    больше нет: в чужом цикле падали запросы к базе.
    """
    from services import status as status_service

    async def собрать():
        return текст

    monkeypatch.setattr(status_service, "collect", собрать)


def test_the_owner_gets_the_report_in_the_chat(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    _подменить_сводку(monkeypatch, "Версия: abc123\n\n🖼 Картинки: все на месте")

    message = FakeMessage(OWNER)
    run(access.owner_status(message))

    assert message.said, "владелец должен получить ответ"
    assert "🖼 Картинки" in "\n".join(message.said)


def test_for_everyone_else_the_command_does_not_exist(monkeypatch):
    """Не «нет доступа», а тишина: чужому знать о команде незачем."""
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    _подменить_сводку(monkeypatch, "секретная сводка")

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
    _подменить_сводку(monkeypatch, long_report)

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


# --- Цикл событий ---------------------------------------------------------
#
# Поймано у Лилии на живом сервере 20 сентября: `/status` отвечал «что-то
# сломалось на моей стороне», а в журнал уходило
# `RuntimeError: ... got Future ... attached to a different loop`
# из `asyncpg/protocol.pyx` — то есть падал самый первый запрос к базе.
#
# Причина: сводка собиралась в отдельном потоке через `asyncio.run`, ради
# обращения к git — оно и правда останавливает весь бот. Но вместе с git
# туда уехали и запросы к базе. Соединение asyncpg принадлежит тому циклу
# событий, в котором открыто; взятое из общего пула в чужом цикле — падает.
#
# Коварство в том, что падает оно не всегда: если пул успел опустеть, в
# новом цикле откроется новое соединение и всё сработает. Поэтому поломка
# выглядела случайной, а команда диагностики оказалась единственной, которая
# не работает.
#
# На SQLite этого не воспроизвести — там соединение к циклу не привязано.
# Значит, проверять надо не «падает ли», а само свойство: сводка обязана
# собираться в том же цикле, в котором её позвали.

def test_the_report_is_collected_in_the_callers_own_loop(monkeypatch):
    """Сводка собирается в том же цикле событий, откуда её позвали.

    Сломай обратно на `asyncio.run` в потоке — и цикл окажется другим.
    """
    from services import status as status_service

    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    увиденный = {}

    async def собрать():
        увиденный["цикл"] = asyncio.get_running_loop()
        return "Версия: abc123"

    monkeypatch.setattr(status_service, "collect", собрать)

    async def сценарий():
        message = FakeMessage(OWNER)
        await access.owner_status(message)
        return asyncio.get_running_loop()

    цикл_вызова = run(сценарий())

    assert увиденный.get("цикл") is цикл_вызова, (
        "сводка собрана в чужом цикле событий — соединения к базе там падают"
    )


def test_no_handler_starts_a_second_event_loop():
    """Ни один обработчик не заводит свой цикл событий.

    База у бота одна на весь процесс, и её соединения принадлежат тому
    циклу, в котором бот живёт. Второй цикл внутри обработчика — это
    поломка, которая проявляется через раз и только на сервере.
    Медленное место уводится в поток отдельно и без обращений к базе.
    """
    from pathlib import Path

    корень = Path(__file__).resolve().parent.parent
    виноватые = []
    for файл in sorted((корень / "handlers").glob("*.py")):
        if "asyncio.run(" in файл.read_text(encoding="utf-8"):
            виноватые.append(файл.name)

    assert not виноватые, (
        f"обработчики заводят свой цикл событий: {', '.join(виноватые)}"
    )
