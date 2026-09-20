"""Копия базы из чата — /backup.

Копии делались и раньше, каждую ночь. Но узнать, делаются ли они, и сделать
свежую можно было только из консоли хостинга — а Лилия работает с айпада и
просила «сделай всё максимально сам». Перед боевым запуском она спросила,
есть ли копия, и ответом было «открой консоль»: то есть в самый нужный
момент страховка зависела от того, откроется ли у неё веб-консоль. Однажды
она уже не открывалась — из-за этого и появился /status.

Здесь проверяется не текст, а три обещания: чужому команды словно нет,
копия делается тем же скриптом, что и ночью, и провал доходит словами.
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import config
from handlers import access
from services import backups
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


def _только_код(исходник: str) -> str:
    """Исходник без комментариев и строк — одни исполняемые слова."""
    import io
    import tokenize

    куски = []
    for вид, текст, *_ in tokenize.generate_tokens(
            io.StringIO(исходник).readline):
        if вид not in (tokenize.COMMENT, tokenize.STRING):
            куски.append(текст)
    return " ".join(куски)


# --- Кому она видна --------------------------------------------------------

def test_for_everyone_else_the_command_does_not_exist(monkeypatch):
    """Не «нет доступа», а тишина: чужому знать о команде незачем.

    Копия базы — это вся переписка, вес и фотографии всех людей разом.
    """
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})

    def нельзя():
        raise AssertionError("чужому копию делать нельзя")

    monkeypatch.setattr(backups, "сделать", нельзя)

    message = FakeMessage(STRANGER)
    run(access.owner_backup(message))
    assert message.said == []


def test_the_owner_check_stands_before_the_work(monkeypatch):
    """Проверка хозяина — до запуска, а не после.

    Иначе копия соберётся у чужого и только потом не отправится: работа
    сделана, диск занят, архив со всеми данными лежит на сервере.
    """
    import inspect

    исходник = inspect.getsource(access.owner_backup)
    проверка = исходник.index("ADMIN_IDS")
    работа = исходник.index("backups")
    assert проверка < работа, "сначала проверяем хозяина, потом работаем"


# --- Что она делает --------------------------------------------------------

def test_the_owner_is_told_before_the_wait_not_after(monkeypatch):
    """Ответ приходит до работы: копия идёт минутами.

    Молчание всё это время человек читает как «команда не сработала» — и
    жмёт ещё раз, получая вторую копию к первой.
    """
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    сказано_до = []

    def медленно():
        сказано_до.append(len(message.said))
        return True, "Копия готова: /root/nutrition-backups/aura-20260920-2100.tar.gz"

    monkeypatch.setattr(backups, "сделать", медленно)
    monkeypatch.setattr(backups, "строки", lambda: ["🗄 Резервные копии"])

    message = FakeMessage(OWNER)
    run(access.owner_backup(message))

    assert сказано_до == [1], "до начала работы человеку уже ответили"
    assert len(message.said) == 2


def test_a_failure_reaches_the_owner_in_words(monkeypatch):
    """«Копии нет» без причины — тупик: следующий шаг из него не придумать."""
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    monkeypatch.setattr(
        backups, "сделать",
        lambda: (False, "pg_dump: ошибка: не удалось подключиться к серверу"))

    message = FakeMessage(OWNER)
    run(access.owner_backup(message))

    целиком = "\n".join(message.said)
    assert "pg_dump" in целиком, "причина обязана дойти словами"
    assert "целы" in целиком, "надо сказать, что данные не пострадали"


def test_the_copy_is_made_by_the_very_same_script_as_at_night():
    """Второй способ копировать разошёлся бы с первым в тот же день.

    Например, забыл бы фотографии — и узнали бы об этом ровно тогда, когда
    копия понадобилась. Поэтому команда зовёт тот же `backup.sh`, который
    стоит в ночном расписании, а не собирает архив по-своему.
    """
    исходник = Path(backups.__file__).read_text(encoding="utf-8")
    assert "backup.sh" in исходник

    # Смотреть надо на исполняемые строки, а не на весь файл: первая версия
    # этой проверки упала на собственном комментарии, где `pg_dump` назван
    # по делу. Сторож, который ловит объяснения вместо кода, заставляет
    # выбирать между понятным комментарием и зелёным тестом.
    assert "pg_dump" not in _только_код(исходник), (
        "копия собирается своими руками — это второй способ копировать")
    for своё in ("tarfile", "shutil.make_archive"):
        assert своё not in исходник, f"своя упаковка архива: {своё}"


# --- Состояние копий -------------------------------------------------------

def test_the_state_tells_when_there_is_nothing_at_all(monkeypatch, tmp_path):
    """Нет копий — это главное, что надо сказать, и сразу что делать."""
    monkeypatch.setattr(backups, "ПАПКА", tmp_path / "пусто")
    monkeypatch.setattr(backups, "_расписание", lambda: False)

    строки = "\n".join(backups.строки())
    assert "копий нет" in строки
    assert "/backup" in строки, "надо назвать, чем это чинится"
    assert "ВЫКЛЮЧЕНО" in строки


def test_the_state_names_the_last_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(backups, "ПАПКА", tmp_path)
    monkeypatch.setattr(backups, "_расписание", lambda: True)
    for имя in ("aura-20260918-0430.tar.gz", "aura-20260920-0430.tar.gz"):
        (tmp_path / имя).write_bytes(b"x" * (3 * 1024 * 1024))

    с = backups.состояние()
    assert с.сколько == 2
    assert с.байты == 3 * 1024 * 1024
    assert с.расписание is True
    строки = "\n".join(backups.строки())
    assert "всего на диске: 2" in строки
    assert "3,0 МБ" in строки


def test_a_missing_systemd_is_not_a_crash(monkeypatch, tmp_path):
    """На стенде и в тестах systemd нет вовсе — сводка не имеет права падать."""
    monkeypatch.setattr(backups, "ПАПКА", tmp_path)
    monkeypatch.setattr(backups, "ЮНИТ", "нет-такого-юнита-12345")
    assert backups._расписание() is False
    assert backups.строки()


# --- Меню ------------------------------------------------------------------

def test_the_command_is_listed_for_the_owner():
    """Команда, о которой не написано, не существует: её не найти."""
    имена = [имя for имя, _ in bot_commands.ADMIN]
    assert "backup" in имена
    подписи = dict(bot_commands.ADMIN)
    assert "копи" in подписи["backup"].lower()


def test_the_public_menu_did_not_grow():
    """Список для всех держится на десяти строках — он не резиновый."""
    assert len(bot_commands.public()) <= 10


# --- Размер копии ----------------------------------------------------------
#
# Поймано у Лилии на живом сервере: строка сказала «последняя копия
# (0 МБ)». Копия была целой — база молодая, её выгрузка весит меньше
# мегабайта, — но деление на мегабайты с округлением вниз показало ноль, а
# «0 МБ» читается как «копия пустая, страховки нет».
#
# Цифра, которая пугает там, где всё в порядке, хуже, чем отсутствие цифры:
# проверять по ней нельзя, а нервничать можно — и в следующий раз, когда
# копия правда не сделается, эту строку уже не прочитают.

def test_a_small_copy_is_never_shown_as_zero(monkeypatch, tmp_path):
    """Копия меньше мегабайта показывается в килобайтах, а не нулём."""
    monkeypatch.setattr(backups, "ПАПКА", tmp_path)
    monkeypatch.setattr(backups, "_расписание", lambda: True)
    (tmp_path / "aura-20260920-0434.tar.gz").write_bytes(b"x" * 700 * 1024)

    строка = "\n".join(backups.строки())
    assert "700 КБ" in строка, строка
    assert "0 МБ" not in строка, "ноль мегабайт читается как «копии нет»"


def test_sizes_are_named_at_every_scale():
    """От пустого файла до гигабайтов — нигде не «0 МБ»."""
    assert backups.вес(0) == "0 байт"
    assert backups.вес(900) == "900 байт"
    assert backups.вес(1024) == "1 КБ"
    assert backups.вес(700 * 1024) == "700 КБ"
    assert backups.вес(1024 * 1024) == "1,0 МБ"
    assert backups.вес(45 * 1024 * 1024) == "45,0 МБ"
    # И ни при каком размере строка не говорит «ноль» о непустом файле.
    for байт in (1, 512, 1023, 1024, 10**5, 10**6, 10**7):
        assert not backups.вес(байт).startswith("0 "), байт


def test_the_console_summary_tells_the_same_size():
    """`bash status.sh` показывает ту же строку — и врал так же.

    Два разных мнения о размере копии в двух местах — это способ однажды
    поверить не тому.
    """
    исходник = Path(backups.__file__).parent.parent / "status.sh"
    текст = исходник.read_text(encoding="utf-8")
    assert "КБ" in текст, "консольная сводка по-прежнему округляет до нуля"
    assert "/ 1024 / 1024 )) МБ" not in текст
