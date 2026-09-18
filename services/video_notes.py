"""Кружки Аи — короткие круглые видео в чате.

Зачем. Анкета спрашивает рост и цель, а живого в этом разговоре нет ничего:
человек отвечает на девять вопросов неизвестно кому. Один кружок в начале и
один в конце превращают это в знакомство.

Где именно и почему только там.

- **Привет** — сразу после согласия с условиями, перед первым вопросом
  анкеты. Этот момент наступает ровно один раз в жизни человека: согласие
  спрашивают, пока его нет, и больше не спрашивают никогда. Поэтому кружок
  не надо отдельно помечать «уже показывали» — он и так придёт однажды.
- **Готово** — после анкеты, вместе с первым шагом. Тоже один раз:
  `onboarding_completed` поднимается однажды.

Больше нигде. Кружки на проблемах — когда человек застрял и ему нужен
ответ — это не помощь, а задержка: тридцать секунд видео со звуком вместо
строчки текста, часто в неудобном месте. Решено не делать (Лилия), и весь
бот живёт по правилу «молчать, когда сказать нечего».

**Нет файла — нет и кружка.** Пока ролики не сняты, бот работает ровно так
же, как работал: ни ошибки, ни пустого сообщения. И если файл окажется
битым, регистрация всё равно должна дойти до конца — человек пришёл
заводить профиль, а не смотреть кино.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import subprocess
import tempfile
from pathlib import Path

import aiohttp
from aiogram.types import FSInputFile, Message

logger = logging.getLogger(__name__)

# Папка с кружками. Лежит в репозитории, а не качается при старте: роликов
# два, они маленькие и меняются раз в полгода — тянуть их по сети значит
# завести ещё одну причину, по которой приветствие однажды не придёт.
CIRCLES_DIR = Path(__file__).resolve().parent.parent / "media" / "circles"

# Что в каком кружке говорится. Текст здесь не для отправки, а чтобы было
# видно, под что снималось: ролик и подпись к нему разъезжаются молча.
CIRCLES: dict[str, str] = {
    "hello": "Привет, я Ая. Сейчас задам несколько вопросов — это пара минут.",
    "ready": "Готово. Открывай приложение — покажу, с чего начать.",
}

# Откуда взять кружок, если его ещё нет на диске. Тот же приём, что у
# фоновых картинок (`services/artwork.py`): ссылка лежит в коде, бот при
# старте проверяет, чего не хватает, и молча докачивает.
#
# Почему не руками. Ролики делает HeyGen, и забрать их файлом из рабочей
# сессии нельзя — прокси не пускает к их хранилищу. Зато у сервера интернет
# открыт, а бот и так перезапускается каждые полчаса: значит, качает он, и
# от человека не требуется ничего.
#
# Ссылки подписанные и живут около недели. Это не страшно: как только файл
# скачался, к ссылке больше не обращаются никогда, а до тех пор у бота
# несколько сотен попыток.
CIRCLE_SOURCES: dict[str, str] = {
    "hello": (
        "https://files2.heygen.ai/aws_pacific/avatar_tmp/4a7788a8687c4e128ff21b469c0fed7a/fd4cfe0f87cd09001bfe4745e5543"
        "e58.mp4?Expires=1790286047&Signature=c0CUf5B1i8UZaYZe8mJ90q5LNL1bUjf1YklvrmO~CVUNbhSFIsPn5cUCcKrUxmPbdRrMv5ij-4nRQM8tb29qA5EMoSjJcPcT2~vlFvBB83TegSlD~ZnK2P8sW1VrW9BCb0L9f6i-7fI-TyiePesDgDj9p6EDi-YuuoHnZf3c3teJreyiitPOihccIdrW17GsQ~De85EBauy0R1bSGw4lZXsBbLEDU0m6cmZjushcHgb-LTbT6EasrK5NOt1XJ8I5ZklC~uMaTSjbhdWxOQK5n58C1WsVlu2w1w9GEQxr2BUgTFTtKLHsoEr8vXN1X4D6aclkTzPdE1BE0iWjy9VRLA__&Key-Pair-Id=K38HBHX5LX3X2H"
    ),
    "ready": (
        "https://files2.heygen.ai/aws_pacific/avatar_tmp/4a7788a8687c4e128ff21b469c0fed7a/768090776a335ea469aea313498d3"
        "69a.mp4?Expires=1790286041&Signature=N-IrS4ze34pWJQLChRy74RDZPj8uFHJu3THCECs4RUNRQpYGasr2bwI3Hy9FKkeb6IyCzrRL0B00SMlA10cCCTZ9afU5LcC2GoMqBkAVgc5614PzpWuEtDxUAUN1ZAN2fmcILVz0hvUwB-MPQ55qc9x5AHkoypX2ByOL3gKWzEUbg02hqjIpF6D-mcPek-lFNbQ2E4~X6oF-0VVgQNgzIYiqIMXKqG7FAUdJ1yO9ljLyPH5EhocFmm35FsMHjzAtsSQPjLdP3MFx2nLL4xHpxVaySQhernR1KaQWFOv-EfR0qwuwripaRqtY0QNMlATI~n6870n3fYIJxTs7~45cKQ__&Key-Pair-Id=K38HBHX5LX3X2H"
    ),
}

# Telegram рисует кружок квадратным и обрезает всё, что в квадрат не влезло.
# Больше минуты он не принимает вовсе.
MAX_SECONDS = 60
# Сторона кадра. Не «на глаз» и не «как пришло»: на 720 живой Telegram
# отвечает `Bad Request: wrong video note length` — его потолок для кружка
# 640. Поймано на сервере у Лилии; отсюда не проверить, к api.telegram.org
# прокси не пускает.
SIDE = 640

# Дольше этого ролик не ждём: кружок не то, ради чего стоит держать старт.
TIMEOUT_SECONDS = 180


def probe(data: bytes) -> tuple[tuple[int, int] | None, float | None]:
    """Сторона кадра и длительность прямо из MP4, без сторонних программ.

    Нужно до установки: кривой файл, положенный в папку, Telegram нарисует
    обрезанным — и заметить это будет некому, кроме человека, который в
    этот момент регистрируется.
    """
    размер: tuple[int, int] | None = None
    секунды: float | None = None
    i = 0
    while i + 8 <= len(data):
        длина = struct.unpack(">I", data[i:i + 4])[0]
        тег = data[i + 4:i + 8].decode("latin1", "replace")
        if длина < 8:
            break
        # В эти коробки заходим внутрь: интересное лежит там.
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
    return размер, секунды


def complaint(data: bytes) -> str | None:
    """Чем плох этот файл **непоправимо** — словами. Всё хорошо — None.

    Сторона здесь не проверяется нарочно: слишком большой кадр — беда
    поправимая, его уменьшает `to_side`. А вот прямоугольник или ролик
    длиннее минуты не чинится ничем.
    """
    размер, секунды = probe(data)
    if размер is None:
        return f"это не похоже на видео ({len(data)} байт)"
    if размер[0] != размер[1]:
        return (f"кадр {размер[0]}×{размер[1]}, а нужен квадрат — "
                "Telegram обрежет всё лишнее")
    if секунды is not None and секунды > MAX_SECONDS:
        return f"{секунды:.0f} секунд, а Telegram берёт не больше {MAX_SECONDS}"
    return None


def to_side(data: bytes) -> tuple[bytes | None, str | None]:
    """Привести квадратный ролик к стороне SIDE. Вернуть (байты, жалоба).

    Зачем вообще. HeyGen меньше 720 квадратных не делает — в его списке
    только 4k, 1080p и 720p. А Telegram на 720 отвечает отказом. Значит,
    уменьшать надо самим, и делать это один раз при установке, а не при
    каждой отправке.

    Перекодирование тут законно, в отличие от роликов тренировок: там
    правило «ставить как есть» защищает движение, снятое художником, а
    здесь выбора нет — иначе кружка не будет вовсе.

    ffmpeg приезжает пакетом `imageio-ffmpeg`, внутри которого собранный
    двоичный файл: ставить что-то в систему на сервере не надо.
    """
    размер, _ = probe(data)
    if размер is None:
        return None, "это не похоже на видео"
    if размер[0] == SIDE:
        return data, None

    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as ошибка:
        return None, (f"кадр {размер[0]}, нужен {SIDE}, а уменьшить нечем: "
                      f"{ошибка}")

    with tempfile.TemporaryDirectory() as папка:
        вход = Path(папка) / "in.mp4"
        выход = Path(папка) / "out.mp4"
        вход.write_bytes(data)
        # Звук переносим как есть: в кружке говорят, и терять голос нельзя.
        # `+faststart` — чтобы оглавление легло в начало файла.
        р = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", str(вход),
             "-vf", f"scale={SIDE}:{SIDE}:flags=lanczos",
             "-c:v", "libx264", "-preset", "medium", "-crf", "23",
             "-pix_fmt", "yuv420p", "-c:a", "copy",
             "-movflags", "+faststart", str(выход)],
            capture_output=True, text=True)
        if р.returncode or not выход.exists():
            хвост = (р.stderr or "").strip().splitlines()[-1:] or ["без объяснений"]
            return None, f"не вышло уменьшить кадр: {хвост[0][:200]}"
        стало = выход.read_bytes()

    проверка = probe(стало)[0]
    if проверка != (SIDE, SIDE):
        return None, f"после уменьшения кадр {проверка}, а нужен {SIDE}×{SIDE}"
    return стало, None


def install(name: str, data: bytes, directory: Path | None = None) -> str | None:
    """Положить кружок на место, если он годный. Вернуть жалобу или None.

    Папка передаётся отдельно ради проверок: сторож, который смотрит на
    рабочую папку, на живом сервере либо трогает настоящие ролики, либо
    молчит из вежливости — и тогда он не сторож.
    """
    if name not in CIRCLES:
        return f"такого кружка нет; бывают: {', '.join(CIRCLES)}"
    беда = complaint(data)
    if беда:
        return беда
    data, беда = to_side(data)
    if беда:
        return беда
    папка = directory or CIRCLES_DIR
    папка.mkdir(parents=True, exist_ok=True)
    # Через временный файл: недокачанный кружок не должен подменить рабочий.
    временный = папка / f"{name}.part"
    временный.write_bytes(data)
    временный.replace(папка / f"{name}.mp4")
    return None


# Что в последний раз пошло не так с каждым кружком — словами. Раньше
# причина уходила только в журнал, а журнал владелице не открыть: она
# работает с айпада. «Кружка нет» без причины — это тупик, из которого
# следующий шаг придумать нельзя.
СБОИ: dict[str, str] = {}


def fix_installed(directory: Path | None = None) -> list[str]:
    """Привести уже лежащие кружки к стороне SIDE. Вернуть имена изменённых.

    Нужно ровно потому, что сначала сюда положили 720: файлы на месте, и
    докачивать нечего, а Telegram их не принимает. Чинить надо то, что уже
    есть, — качать заново незачем и нечем, ссылки живут неделю.

    Тихо не падаем: не вышло — записываем причину и оставляем как было.
    Битый файл на месте рабочего хуже, чем неподходящий.
    """
    изменены: list[str] = []
    for имя in CIRCLES:
        путь = circle_path(имя, directory)
        if путь is None:
            continue
        было = путь.read_bytes()
        размер, _ = probe(было)
        if размер == (SIDE, SIDE):
            continue
        стало, беда = to_side(было)
        if беда or not стало:
            СБОИ[имя] = f"кадр {размер}, привести к {SIDE} не вышло: {беда}"
            logger.warning("Кружок %s не ужался: %s", имя, беда)
            continue
        временный = путь.with_suffix(".part")
        временный.write_bytes(стало)
        временный.replace(путь)
        СБОИ.pop(имя, None)
        изменены.append(имя)
        logger.info("Кружок %s приведён к %d×%d", имя, SIDE, SIDE)
    return изменены


async def ensure_circles(directory: Path | None = None) -> list[str]:
    """Докачать недостающие кружки. Падать из-за них бот не должен.

    Вызывается фоном при старте, как и картинки: без кружков приложение
    работает целиком, ждать их незачем. Возвращает имена тех, что встали
    именно сейчас, — чтобы вызвавший мог сказать об этом вслух.
    """
    # Сначала лечим уже лежащее: файл на месте, но не той стороны — это
    # не «нечего делать», а именно то, из-за чего кружок не приходит.
    fix_installed(directory)
    нужны = [имя for имя in CIRCLE_SOURCES if circle_path(имя, directory) is None]
    if not нужны:
        return []
    встали: list[str] = []
    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for имя in нужны:
                try:
                    async with session.get(CIRCLE_SOURCES[имя]) as ответ:
                        ответ.raise_for_status()
                        data = await ответ.read()
                except Exception as ошибка:
                    СБОИ[имя] = f"не скачался: {ошибка}"
                    logger.warning("Кружок %s не скачался: %s", имя, ошибка)
                    continue
                беда = install(имя, data, directory)
                if беда:
                    СБОИ[имя] = f"пришёл негодным: {беда}"
                    logger.warning("Кружок %s не поставлен: %s", имя, беда)
                else:
                    СБОИ.pop(имя, None)
                    встали.append(имя)
                    logger.info("Кружок %s готов (%.1f МБ)", имя, len(data) / 2**20)
    except asyncio.CancelledError:
        raise
    except Exception as ошибка:
        for имя in нужны:
            СБОИ.setdefault(имя, f"скачать не вышло: {ошибка}")
        logger.warning("Кружки скачать не вышло — идём дальше", exc_info=True)
    return встали


def circle_path(name: str, directory: Path | None = None) -> Path | None:
    """Файл кружка, если он есть. Нет файла — None, и это не ошибка."""
    if name not in CIRCLES:
        raise KeyError(f"неизвестный кружок: {name}")
    path = (directory or CIRCLES_DIR) / f"{name}.mp4"
    return path if path.is_file() else None



def состояние(name: str, directory: Path | None = None) -> str:
    """Что сейчас с этим кружком — одной строкой, словами.

    Нужно владелице: «кружка нет» без причины — тупик, из которого
    следующий шаг придумать нельзя, а в журнал на сервере она не смотрит.
    """
    путь = circle_path(name, directory)
    if путь is None:
        беда = СБОИ.get(name)
        return f"файла нет ({беда})" if беда else "файла нет, и причина неизвестна"
    данные = путь.read_bytes()
    размер, секунды = probe(данные)
    куски = [f"{len(данные) / 2**20:.1f} МБ"]
    if размер:
        куски.append(f"{размер[0]}×{размер[1]}")
    if секунды:
        куски.append(f"{секунды:.0f} с")
    строка = "на месте: " + ", ".join(куски)
    беда = СБОИ.get(name)
    return f"{строка}; в прошлый раз {беда}" if беда else строка

async def send_circle(message: Message, name: str) -> bool:
    """Отправить кружок. Вернуть, отправился ли.

    Ошибку глотаем нарочно: человек пришёл заводить профиль, и если ролик
    не залился, анкета всё равно обязана пойти дальше.
    """
    path = circle_path(name)
    if path is None:
        return False
    try:
        await message.answer_video_note(FSInputFile(path), length=SIDE)
        СБОИ.pop(name, None)
        return True
    except Exception as ошибка:
        СБОИ[name] = f"Telegram не принял файл: {ошибка}"
        logger.warning("Кружок %s не отправился — идём дальше", name, exc_info=True)
        return False
