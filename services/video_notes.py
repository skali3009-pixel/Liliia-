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
# Сторона кадра. Ровно та, в которой сняты кружки: `length` — это подсказка
# Telegram о размере, и врать в ней значит просить телефон нарисовать круг
# не того размера, что пришёл.
SIDE = 720

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
    """Чем плох этот файл — словами. Всё хорошо — None."""
    размер, секунды = probe(data)
    if размер is None:
        return f"это не похоже на видео ({len(data)} байт)"
    if размер[0] != размер[1]:
        return (f"кадр {размер[0]}×{размер[1]}, а нужен квадрат — "
                "Telegram обрежет всё лишнее")
    if размер[0] != SIDE:
        return f"сторона {размер[0]}, а бот обещает Telegram {SIDE}"
    if секунды is not None and секунды > MAX_SECONDS:
        return f"{секунды:.0f} секунд, а Telegram берёт не больше {MAX_SECONDS}"
    return None


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
    папка = directory or CIRCLES_DIR
    папка.mkdir(parents=True, exist_ok=True)
    # Через временный файл: недокачанный кружок не должен подменить рабочий.
    временный = папка / f"{name}.part"
    временный.write_bytes(data)
    временный.replace(папка / f"{name}.mp4")
    return None


async def ensure_circles(directory: Path | None = None) -> None:
    """Докачать недостающие кружки. Падать из-за них бот не должен.

    Вызывается фоном при старте, как и картинки: без кружков приложение
    работает целиком, ждать их незачем.
    """
    нужны = [имя for имя in CIRCLE_SOURCES if circle_path(имя, directory) is None]
    if not нужны:
        return
    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for имя in нужны:
                try:
                    async with session.get(CIRCLE_SOURCES[имя]) as ответ:
                        ответ.raise_for_status()
                        data = await ответ.read()
                except Exception as ошибка:
                    logger.warning("Кружок %s не скачался: %s", имя, ошибка)
                    continue
                беда = install(имя, data, directory)
                if беда:
                    logger.warning("Кружок %s не поставлен: %s", имя, беда)
                else:
                    logger.info("Кружок %s готов (%.1f МБ)", имя, len(data) / 2**20)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Кружки скачать не вышло — идём дальше", exc_info=True)


def circle_path(name: str, directory: Path | None = None) -> Path | None:
    """Файл кружка, если он есть. Нет файла — None, и это не ошибка."""
    if name not in CIRCLES:
        raise KeyError(f"неизвестный кружок: {name}")
    path = (directory or CIRCLES_DIR) / f"{name}.mp4"
    return path if path.is_file() else None


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
        return True
    except Exception:
        logger.warning("Кружок %s не отправился — идём дальше", name, exc_info=True)
        return False
