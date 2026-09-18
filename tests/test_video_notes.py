"""Кружки Аи: два, и только на входе.

Здесь заперто главное: пока роликов нет, бот обязан работать ровно так же,
как работал. Молчаливое «регистрация не дошла до конца, потому что не
залилось видео» — худшее, что может случиться с первым знакомством.
"""

import asyncio
import inspect
import struct
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from services.video_notes import (CIRCLE_SOURCES, CIRCLES, CIRCLES_DIR,
                                  MAX_SECONDS, SIDE, circle_path, complaint,
                                  ensure_circles, install, probe, send_circle)

ROOT = Path(__file__).resolve().parents[1]
LEGAL = (ROOT / "handlers" / "legal.py").read_text(encoding="utf-8")
ONBOARDING = (ROOT / "handlers" / "onboarding.py").read_text(encoding="utf-8")
ACCESS = (ROOT / "handlers" / "access.py").read_text(encoding="utf-8")

# Где кружкам стоять позволено — и больше нигде. Третье место появилось
# позже двух первых: у Лилии профиль давно заведён, и оба одноразовых
# момента она пропустила, а знать, что получает новый человек, ей надо.
РАЗРЕШЕНО = {"legal.py", "onboarding.py", "access.py"}


class ФейковоеСообщение:
    """Сообщение, которое запоминает отправленное и умеет ломаться."""

    def __init__(self, падает=False):
        self.отправлено = []
        self.падает = падает

    async def answer_video_note(self, файл, length=None):
        if self.падает:
            raise RuntimeError("Telegram не принял файл")
        self.отправлено.append((файл, length))


def коробка(тег: bytes, тело: bytes) -> bytes:
    return struct.pack(">I", len(тело) + 8) + тег + тело


def ролик(ширина: int, высота: int, секунды: float = 8.0) -> bytes:
    """Крошечный MP4 ровно из тех коробок, по которым смотрит probe."""
    mvhd = коробка(b"mvhd", b"\x00" * 12 + struct.pack(">II", 1000, int(секунды * 1000))
                   + b"\x00" * 80)
    tkhd = b"\x00" * 76 + struct.pack(">II", ширина << 16, высота << 16)
    trak = коробка(b"trak", коробка(b"mdia", коробка(b"tkhd", tkhd)))
    return коробка(b"ftyp", b"isom" + b"\x00" * 8) + коробка(b"moov", mvhd + trak)


def квадратный_ролик() -> bytes:
    return ролик(SIDE, SIDE)


def прямоугольный_ролик() -> bytes:
    return ролик(640, 360)


class Раздатчик(BaseHTTPRequestHandler):
    """Отдаёт один годный кружок и молчит в журнал."""

    def do_GET(self):
        тело = квадратный_ролик()
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(тело)))
        self.end_headers()
        self.wfile.write(тело)

    def log_message(self, *args):
        pass


def test_there_are_exactly_two_circles_and_both_are_at_the_entrance():
    """Кружки на проблемах решено не делать: человеку, который застрял,
    нужен ответ строкой, а не тридцать секунд видео со звуком."""
    assert set(CIRCLES) == {"hello", "ready"}
    # «Привет» — после согласия, «Готово» — после анкеты. Больше нигде.
    assert 'send_circle(callback.message, "hello")' in LEGAL
    assert 'send_circle(message, "ready")' in ONBOARDING
    assert LEGAL.count("send_circle(") == 1
    assert ONBOARDING.count("send_circle(") == 1

    # И ни в одном другом разговоре кружок не всплывает.
    где = {путь.name for путь in (ROOT / "handlers").glob("*.py")
           if "send_circle(" in путь.read_text(encoding="utf-8")}
    assert где == РАЗРЕШЕНО, где ^ РАЗРЕШЕНО


def test_the_owners_preview_is_closed_to_everyone_else():
    """Третье место — показ владелице, и он обязан быть только для неё.

    Открытый всем, он превратился бы в кнопку «покажи кино»: кружок
    перестал бы быть встречей и стал бы развлечением, а бот живёт по
    правилу «молчать, когда сказать нечего».
    """
    кусок = ACCESS.split('@router.message(Command("circles"))', 1)[1]
    тело = кусок.split("\n@router", 1)[0]
    assert "send_circle(" in тело, "показ уехал из своего обработчика"
    # Проверка хозяина стоит до первой отправки, а не где-нибудь ниже.
    проверка = тело.index("config.ADMIN_IDS")
    assert проверка < тело.index("send_circle("), "показ идёт до проверки хозяина"
    assert "return" in тело[проверка:проверка + 120], "проверка ничего не обрывает"

    # И команда не попала в общий список, где её увидят все.
    from services import commands as bot_commands
    assert "circles" not in {имя for имя, _ in bot_commands.public()}
    assert "circles" in {имя for имя, _ in bot_commands.admin()}


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
    """Забытый await — это «кружок не пришёл», и никакой ошибки.

    Требовать, чтобы строка начиналась с `await`, нельзя: вызов законно
    стоит и внутри условия («не отправился — скажи словами»). Важно
    только одно — что его дожидаются.
    """
    for текст in (LEGAL, ONBOARDING, ACCESS):
        for строка in текст.splitlines():
            if "send_circle(" in строка and "import" not in строка:
                до = строка.split("send_circle(")[0]
                assert до.rstrip().endswith("await"), строка


def test_the_installed_files_fit_what_telegram_draws():
    """Telegram рисует кружок квадратным и режет всё, что не влезло.

    Проверка идёт только по тем файлам, которые уже лежат: пока их нет,
    проверять нечего, а когда появятся — они обязаны быть квадратными и
    короткими, иначе у Аи срежет половину лица.
    """
    assert MAX_SECONDS == 60 and SIDE == 640
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


def test_the_bot_fetches_the_circles_itself():
    """От человека для этого не требуется ничего.

    Забрать ролики файлом из рабочей сессии нельзя — прокси не пускает к
    хранилищу HeyGen. Зато у сервера интернет открыт, а бот и так
    перезапускается каждые полчаса: значит, качает он. Тот же приём, что у
    фоновых картинок.
    """
    assert set(CIRCLE_SOURCES) == set(CIRCLES), set(CIRCLE_SOURCES) ^ set(CIRCLES)
    for имя, ссылка in CIRCLE_SOURCES.items():
        assert ссылка.startswith("https://"), имя

    старт = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert "ensure_circles()" in старт
    # Фоном, как картинки: без кружков регистрация идёт как шла.
    assert "asyncio.create_task(ensure_circles())" in старт
    # И задача снимается на выходе — иначе она переживёт бота.
    assert "circles_task.cancel()" in старт


def test_a_download_that_fails_does_not_stop_the_bot(tmp_path):
    """Сеть отвалилась, ссылка протухла — бот всё равно встаёт.

    Проверяется на заведомо недоступном адресе и в пустой папке: наружу не
    должно вылететь ничего, и мусор в папке появиться тоже не должен.
    """
    было = dict(CIRCLE_SOURCES)
    CIRCLE_SOURCES.clear()
    CIRCLE_SOURCES["hello"] = "https://127.0.0.1:1/нет.mp4"
    try:
        asyncio.run(ensure_circles(tmp_path))    # не должно бросить наружу
    finally:
        CIRCLE_SOURCES.clear()
        CIRCLE_SOURCES.update(было)
    assert list(tmp_path.iterdir()) == []
    assert circle_path("hello", tmp_path) is None


def test_one_circle_falling_does_not_take_the_other_with_it(tmp_path):
    """Ссылки подписанные и протухают порознь.

    Если первая уже мертва, а вторая жива, забрать надо вторую. Без этого
    один просроченный адрес молча оставлял бы человека без обоих роликов.
    """
    сервер = HTTPServer(("127.0.0.1", 0), Раздатчик)
    поток = threading.Thread(target=сервер.serve_forever, daemon=True)
    поток.start()
    адрес = f"http://127.0.0.1:{сервер.server_address[1]}/ready.mp4"

    было = dict(CIRCLE_SOURCES)
    CIRCLE_SOURCES.clear()
    CIRCLE_SOURCES["hello"] = "https://127.0.0.1:1/нет.mp4"
    CIRCLE_SOURCES["ready"] = адрес
    try:
        asyncio.run(ensure_circles(tmp_path))
    finally:
        CIRCLE_SOURCES.clear()
        CIRCLE_SOURCES.update(было)
        сервер.shutdown()

    assert circle_path("hello", tmp_path) is None
    assert circle_path("ready", tmp_path) is not None
    assert (tmp_path / "ready.mp4").read_bytes() == квадратный_ролик()


def test_a_bad_file_never_reaches_the_folder(tmp_path):
    """Кривой кружок Telegram нарисует обрезанным, и заметить это будет
    некому — кроме человека, который в этот момент регистрируется."""
    # Не видео вовсе.
    assert install("hello", b"\x00" * 500, tmp_path) is not None
    # Прямоугольный кадр: Telegram обрежет всё, что не влезло в круг.
    assert install("hello", прямоугольный_ролик(), tmp_path) is not None
    # Имя, которого нет: опечатка в коде, а не молчание.
    assert install("нет_такого", b"", tmp_path) is not None
    # Ни один из них до папки не доехал.
    assert list(tmp_path.iterdir()) == []
    assert circle_path("hello", tmp_path) is None

    # А годный — доехал, и лежит под своим именем.
    assert install("hello", квадратный_ролик(), tmp_path) is None
    assert circle_path("hello", tmp_path) == tmp_path / "hello.mp4"
    # Временного файла после установки не остаётся.
    assert not (tmp_path / "hello.part").exists()

    # И жалобы говорят словами, что именно не так.
    assert "не похоже на видео" in complaint(b"\x00" * 500)
    assert "квадрат" in complaint(прямоугольный_ролик())


def test_the_check_lives_in_one_place():
    """Двух разных мнений о том, какой файл годный, в проекте быть не должно.

    Ручной скрипт и загрузчик бота обязаны спрашивать одну и ту же функцию:
    иначе однажды один поставит то, что другой отверг бы.
    """
    ручной = (ROOT / "services" / "fetch_circles.py").read_text(encoding="utf-8")
    assert "from services.video_notes import" in ручной
    assert "install(имя, data)" in ручной
    # Своей проверки геометрии у скрипта не осталось.
    assert "struct.unpack" not in ручной


def test_the_service_says_what_each_circle_is_about():
    """Ролик и подпись к нему разъезжаются молча — пусть лежат рядом."""
    for имя, текст in CIRCLES.items():
        assert len(текст) > 20, имя
    assert "Ая" in CIRCLES["hello"]
    assert inspect.getdoc(send_circle)

def test_the_owner_is_not_told_to_wait_half_an_hour():
    """Кружков нет — команда качает их прямо сейчас, а не отсылает ждать.

    Раньше она отвечала «бот дотянет их при следующем перезапуске».
    Перезапуск раз в полчаса: чтобы увидеть своё же приветствие, надо было
    ждать полчаса — это не ответ, а отписка. Качать бот умеет и сам.
    """
    кусок = ACCESS.split('@router.message(Command("circles"))', 1)[1]
    тело = кусок.split("\n@router", 1)[0]
    assert "await ensure_circles()" in тело, "команда не пробует докачать"
    # Смотрим на то, что бот говорит человеку, а не на пояснение для себя:
    # в пояснении слово «перезапуск» стоит законно — там сказано, почему
    # отсылать к нему нельзя.
    без_пояснения = тело.split('"""', 2)[-1]
    assert "перезапуск" not in без_пояснения.lower(), "команда всё ещё отсылает ждать"


def test_a_failure_reaches_the_owner_in_words(tmp_path):
    """«Кружка нет» без причины — тупик: следующий шаг из него не придумать.

    Причина жила только в журнале на сервере, а владелица работает с
    айпада и туда не смотрит.
    """
    from services.video_notes import СБОИ, состояние

    было = dict(CIRCLE_SOURCES)
    СБОИ.clear()
    CIRCLE_SOURCES.clear()
    CIRCLE_SOURCES["hello"] = "https://127.0.0.1:1/нет.mp4"
    try:
        asyncio.run(ensure_circles(tmp_path))
    finally:
        CIRCLE_SOURCES.clear()
        CIRCLE_SOURCES.update(было)

    assert "hello" in СБОИ, "причина не запомнилась"
    рассказ = состояние("hello", tmp_path)
    assert "файла нет" in рассказ and "не скачался" in рассказ, рассказ

    # А когда файл на месте, рассказ называет размер кадра — по нему и
    # видно, тот ли файл доехал.
    assert install("hello", квадратный_ролик(), tmp_path) is None
    рассказ = состояние("hello", tmp_path)
    assert "на месте" in рассказ and f"{SIDE}×{SIDE}" in рассказ, рассказ
    СБОИ.clear()


def test_a_refusal_from_telegram_is_remembered_too(tmp_path):
    """Файл на месте, а кружок не пришёл — это третий случай, и молчать
    о нём нельзя: снаружи он неотличим от «файла нет»."""
    from services.video_notes import СБОИ, состояние

    СБОИ.clear()
    assert install("ready", квадратный_ролик(), tmp_path) is None
    сообщение = ФейковоеСообщение(падает=True)
    # Отправка смотрит в рабочую папку, поэтому проверяем саму память о сбое.
    СБОИ["ready"] = "Telegram не принял файл: VIDEO_NOTE_DIMENSIONS_INVALID"
    assert "Telegram не принял" in состояние("ready", tmp_path)
    СБОИ.clear()

def test_the_bot_keeps_trying_until_the_circles_are_there(tmp_path):
    """Одной попытки при запуске мало.

    Сеть могла моргнуть ровно в ту секунду, а перезапуск бывает только
    когда выходит новая версия — на тихой неделе его может не случиться
    вовсе, и новые люди всё это время приходили бы без приветствия.
    """
    расписание = (ROOT / "scheduler.py").read_text(encoding="utf-8")
    assert "from services.video_notes import ensure_circles" in расписание
    assert 'scheduler.add_job(ensure_circles, "interval"' in расписание, \
        "повторной попытки в планировщике нет"


def test_the_retry_costs_nothing_once_the_files_are_in_place(tmp_path):
    """Задача крутится постоянно, поэтому на готовых файлах она обязана
    молчать: ходить в чужое хранилище каждые двадцать минут без надобности
    — это и лишний трафик, и лишний повод протухшей ссылке нашуметь."""
    assert install("hello", квадратный_ролик(), tmp_path) is None
    assert install("ready", квадратный_ролик(), tmp_path) is None

    было = dict(CIRCLE_SOURCES)
    CIRCLE_SOURCES.clear()
    # Адрес заведомо мёртвый: если задача в сеть полезет, будет видно по
    # записанной беде.
    CIRCLE_SOURCES.update({имя: "https://127.0.0.1:1/нет.mp4" for имя in CIRCLES})
    from services.video_notes import СБОИ
    СБОИ.clear()
    try:
        встали = asyncio.run(ensure_circles(tmp_path))
    finally:
        CIRCLE_SOURCES.clear()
        CIRCLE_SOURCES.update(было)
    assert встали == [], встали
    assert СБОИ == {}, "задача ходила в сеть, хотя файлы на месте"

def настоящий_ролик(сторона: int, секунд: int = 6) -> bytes:
    """Живой MP4 со звуком — подделкой из коробок тут не обойтись.

    Уменьшение кадра проверяется настоящим кодировщиком, а он на выдуманных
    коробках работать не станет. Без такого теста правило «640» держалось бы
    на слове.
    """
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as папка:
        файл = Path(папка) / "v.mp4"
        subprocess.run(
            [ff, "-v", "error", "-y", "-f", "lavfi",
             "-i", f"testsrc=size={сторона}x{сторона}:rate=25:duration={секунд}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={секунд}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", str(файл)], check=True)
        return файл.read_bytes()


def test_a_720_circle_is_brought_down_to_what_telegram_accepts(tmp_path):
    """HeyGen меньше 720 квадратных не делает, а Telegram 720 не принимает.

    Живой ответ сервера: `Bad Request: wrong video note length`. Значит,
    уменьшать надо самим, и на установке, а не на каждой отправке.
    """
    исход = настоящий_ролик(720)
    assert probe(исход)[0] == (720, 720)
    # Слишком большой кадр — беда поправимая, и жалобой она быть не должна.
    assert complaint(исход) is None

    assert install("hello", исход, tmp_path) is None
    лежит = (tmp_path / "hello.mp4").read_bytes()
    assert probe(лежит)[0] == (SIDE, SIDE), probe(лежит)


def test_the_voice_survives_the_resize(tmp_path):
    """В кружке говорят. Потерять звук значит потерять сам смысл."""
    import imageio_ffmpeg
    assert install("ready", настоящий_ролик(720), tmp_path) is None
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    сведения = subprocess.run([ff, "-hide_banner", "-i", str(tmp_path / "ready.mp4")],
                              capture_output=True, text=True).stderr
    assert "Audio:" in сведения, сведения[-400:]


def test_circles_already_on_disk_get_fixed_in_place(tmp_path):
    """Файлы уже лежали в 720: докачивать нечего, а Telegram их не берёт.

    Чинить надо то, что есть. Качать заново нечем — подписанные ссылки
    живут около недели.
    """
    for имя in CIRCLES:
        (tmp_path / f"{имя}.mp4").write_bytes(настоящий_ролик(720))

    from services.video_notes import fix_installed
    assert sorted(fix_installed(tmp_path)) == sorted(CIRCLES)
    for имя in CIRCLES:
        assert probe((tmp_path / f"{имя}.mp4").read_bytes())[0] == (SIDE, SIDE)

    # Второй заход не трогает ничего: лечение не должно жевать файл по кругу.
    assert fix_installed(tmp_path) == []
