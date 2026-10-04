"""Доступ Тимура из чата — /timur.

Серийная консоль у Лилии перестала отвечать: вставленное оставалось на
экране и до сервера не доходило. Поэтому доступ выдаёт сам бот, тем же
`grant-timur.sh`, что и из консоли.

Обещания: чужому команды словно нет, строка из чата в аргументы скрипта не
попадает, запускается тот самый скрипт, и итог доходит словами — и удача,
и провал.
"""

import asyncio
import inspect
import stat

import config
from handlers import access
from services import commands as bot_commands
from services import server_access

OWNER = 777
STRANGER = 42


class FakeMessage:
    def __init__(self, user_id, text="/timur"):
        self.from_user = type("U", (), {"id": user_id})()
        self.text = text
        self.said: list[str] = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        return self


def run(coro):
    return asyncio.run(coro)


def test_for_everyone_else_the_command_does_not_exist(monkeypatch):
    """Не «нет доступа», а тишина: это вход на сервер с правами sudo."""
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})

    def нельзя(*_):
        raise AssertionError("чужому скрипт запускать нельзя")

    monkeypatch.setattr(server_access, "выполнить", нельзя)
    message = FakeMessage(STRANGER)
    run(access.owner_grant_timur(message))
    assert message.said == []


def test_the_owner_check_stands_before_the_work():
    исходник = inspect.getsource(access.owner_grant_timur)
    assert исходник.index("ADMIN_IDS") < исходник.index("server_access.выполнить")


def test_words_from_the_chat_never_become_arguments():
    """В скрипт уходит только один из трёх заранее известных режимов."""
    assert server_access.режим("/timur") == []
    assert server_access.режим("/timur проверить") == ["--check"]
    assert server_access.режим("/timur  Убрать ") == ["--remove"]
    for чужое in ("/timur --remove; id", "/timur ../x", "/timur --check extra",
                  "/timur rm -rf /"):
        assert server_access.режим(чужое) is None, чужое


def test_an_unknown_word_gets_help_not_the_script(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    monkeypatch.setattr(server_access, "выполнить",
                        lambda *_: (_ for _ in ()).throw(AssertionError("не звать")))
    message = FakeMessage(OWNER, "/timur что-то")
    run(access.owner_grant_timur(message))
    assert len(message.said) == 1 and "/timur убрать" in message.said[0]


def test_the_owner_is_told_before_the_work_and_gets_the_result(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    звали = []

    def выполнить(аргументы):
        звали.append(аргументы)
        return True, "Готово. Для Тимура:  ssh -p 22 timur@72.56.90.120"

    monkeypatch.setattr(server_access, "выполнить", выполнить)
    message = FakeMessage(OWNER, "/timur")
    run(access.owner_grant_timur(message))
    assert звали == [[]]
    assert len(message.said) == 2
    assert "несколько секунд" in message.said[0]
    assert message.said[1].startswith("✅") and "timur@72.56.90.120" in message.said[1]


def test_a_failure_reaches_the_owner_in_words(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    monkeypatch.setattr(server_access, "выполнить",
                        lambda _: (False, "✗ на сервере нет sudo"))
    message = FakeMessage(OWNER)
    run(access.owner_grant_timur(message))
    assert message.said[-1].startswith("🛑") and "нет sudo" in message.said[-1]


def test_it_runs_the_very_same_script_as_the_console(monkeypatch, tmp_path):
    """Второго способа выдавать доступ нет: скрипт тот же, аргументы те же."""
    assert server_access.СКРИПТ.name == "grant-timur.sh"
    assert server_access.СКРИПТ.exists()

    подмена = tmp_path / "grant-timur.sh"
    подмена.write_text('echo "args:$*"; read x && echo "stdin:$x"; exit 0\n')
    подмена.chmod(подмена.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(server_access, "СКРИПТ", подмена)

    получилось, вывод = server_access.выполнить(["--check"])
    assert получилось
    assert "args:--check" in вывод
    # Ввода у скрипта нет: ждущий вопрос не должен вешать поток бота.
    assert "stdin:" not in вывод


def test_a_missing_script_is_said_not_crashed(monkeypatch, tmp_path):
    monkeypatch.setattr(server_access, "СКРИПТ", tmp_path / "нет.sh")
    получилось, вывод = server_access.выполнить([])
    assert not получилось and "не найден" in вывод


def test_the_command_is_listed_for_the_owner_only():
    assert "timur" in dict(bot_commands.ADMIN)
    assert all(имя != "timur" for имя, _ in bot_commands.public())


def test_the_script_gets_no_input_from_the_bot(monkeypatch):
    """Ввод закрыт явно. Унаследованный от службы ввод мог бы оказаться
    открытым, и любой вопрос скрипта молча держал бы поток бота до предела."""
    увидено = {}

    def run(*args, **kwargs):
        увидено.update(kwargs)
        raise OSError("не запускаем")

    monkeypatch.setattr(server_access.subprocess, "run", run)
    server_access.выполнить([])
    assert увидено.get("stdin") is server_access.subprocess.DEVNULL
    assert увидено.get("timeout") == server_access.ПРЕДЕЛ_СЕК
