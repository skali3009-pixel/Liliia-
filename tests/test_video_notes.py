"""Кружки Аи: два, и только на входе.

Здесь заперто главное: пока роликов нет, бот обязан работать ровно так же,
как работал. Молчаливое «регистрация не дошла до конца, потому что не
залилось видео» — худшее, что может случиться с первым знакомством.
"""

import asyncio
import inspect
from pathlib import Path

import pytest

from services.video_notes import (CIRCLES, CIRCLES_DIR, MAX_SECONDS, SIDE,
                                  circle_path, send_circle)

ROOT = Path(__file__).resolve().parents[1]
LEGAL = (ROOT / "handlers" / "legal.py").read_text(encoding="utf-8")
ONBOARDING = (ROOT / "handlers" / "onboarding.py").read_text(encoding="utf-8")


class ФейковоеСообщение:
    """Сообщение, которое запоминает отправленное и умеет ломаться."""

    def __init__(self, падает=False):
        self.отправлено = []
        self.падает = падает

    async def answer_video_note(self, файл, length=None):
        if self.падает:
            raise RuntimeError("Telegram не принял файл")
        self.отправлено.append((файл, length))


def test_there_are_exactly_two_circles_and_both_are_at_the_entrance():
    """Кружки на проблемах решено не делать: человеку, который застрял,
    нужен ответ строкой, а не тридцать секунд видео со звуком."""
    assert set(CIRCLES) == {"hello", "ready"}
    # «Привет» — после согласия, «Готово» — после анкеты. Больше нигде.
    assert 'send_circle(callback.message, "hello")' in LEGAL
    assert 'send_circle(message, "ready")' in ONBOARDING
    assert LEGAL.count("send_circle(") == 1
    assert ONBOARDING.count("send_circle(") == 1


def test_each_moment_happens_once_in_a_persons_life():
    """Иначе кружок придёт на каждый /start, и это навязчивость.

    Отдельной отметки «уже показывали» нет нарочно: согласие спрашивают,
    пока его нет, а `onboarding_completed` поднимается однажды. Момент сам
    по себе одноразовый — лишняя колонка в базе тут только добавила бы
    способов разъехаться.
    """
    # «Привет» стоит в обработчике согласия, а не в /start.
    кусок = LEGAL.split('send_circle(callback.message, "hello")', 1)[0]
    assert "marketing_consent" in кусок
    # «Готово» — после того, как анкета записана и профиль закрыт.
    кусок = ONBOARDING.split('send_circle(message, "ready")', 1)[0]
    assert "user.onboarding_completed = True" in кусок


def test_without_the_files_nothing_is_sent_and_nothing_breaks():
    """Пока ролики не сняты, бот работает как работал."""
    for имя in CIRCLES:
        путь = circle_path(имя)
        # Файла может не быть — это штатное состояние, а не поломка.
        assert путь is None or путь.is_file()

    сообщение = ФейковоеСообщение()
    if circle_path("hello") is None:
        assert asyncio.run(send_circle(сообщение, "hello")) is False
        assert сообщение.отправлено == []


def test_a_broken_file_never_stops_the_registration():
    """Человек пришёл заводить профиль, а не смотреть кино.

    Проверяется на живой функции: подсовываем сообщение, которое падает при
    отправке, и ждём спокойного False вместо исключения наружу.
    """
    CIRCLES_DIR.mkdir(parents=True, exist_ok=True)
    подделка = CIRCLES_DIR / "hello.mp4"
    своё = not подделка.exists()
    if своё:
        подделка.write_bytes("не настоящий ролик".encode("utf-8"))
    try:
        сообщение = ФейковоеСообщение(падает=True)
        assert asyncio.run(send_circle(сообщение, "hello")) is False
    finally:
        if своё:
            подделка.unlink()


def test_an_unknown_circle_is_a_mistake_in_the_code_and_says_so():
    """Опечатка в имени не должна превращаться в молчание."""
    with pytest.raises(KeyError):
        circle_path("privet")


def test_the_circles_are_sent_and_awaited():
    """Забытый await — это «кружок не пришёл», и никакой ошибки."""
    for текст in (LEGAL, ONBOARDING):
        for строка in текст.splitlines():
            if "send_circle(" in строка and "import" not in строка:
                assert строка.strip().startswith("await "), строка


def test_the_installed_files_fit_what_telegram_draws():
    """Telegram рисует кружок квадратным и режет всё, что не влезло.

    Проверка идёт только по тем файлам, которые уже лежат: пока их нет,
    проверять нечего, а когда появятся — они обязаны быть квадратными и
    короткими, иначе у Аи срежет половину лица.
    """
    assert MAX_SECONDS == 60 and SIDE == 720
    import struct

    for имя in CIRCLES:
        путь = circle_path(имя)
        if путь is None:
            continue
        data = путь.read_bytes()
        размер, секунды = None, None
        i = 0
        while i + 8 <= len(data):
            длина = struct.unpack(">I", data[i:i + 4])[0]
            тег = data[i + 4:i + 8].decode("latin1", "replace")
            if длина < 8:
                break
            if тег in ("moov", "trak", "mdia"):
                i += 8
                continue
            if тег == "mvhd":
                масштаб, длит = struct.unpack(">II", data[i + 20:i + 28])
                секунды = длит / масштаб if масштаб else None
            if тег == "tkhd":
                ш = struct.unpack(">I", data[i + 84:i + 88])[0] >> 16
                в = struct.unpack(">I", data[i + 88:i + 92])[0] >> 16
                if ш and в:
                    размер = (ш, в)
            i += длина
        assert размер is not None, имя
        assert размер[0] == размер[1], (имя, размер)
        # И сторона та самая, которую бот обещает Telegram.
        assert размер[0] == SIDE, (имя, размер, SIDE)
        assert секунды is None or секунды <= MAX_SECONDS, (имя, секунды)


def test_the_service_says_what_each_circle_is_about():
    """Ролик и подпись к нему разъезжаются молча — пусть лежат рядом."""
    for имя, текст in CIRCLES.items():
        assert len(текст) > 20, имя
    assert "Ая" in CIRCLES["hello"]
    assert inspect.getdoc(send_circle)
