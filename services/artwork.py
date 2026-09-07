"""Фоновые арты приложения: скачиваются сами при запуске.

Картинки не лежат в git — они большие и меняются отдельно от кода. Бот
при старте проверяет, что все на месте, и молча докачивает недостающие.
Если сеть недоступна, приложение просто покажет градиентное ночное небо:
падать из-за картинок бот не должен.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

ART_DIR = Path(__file__).resolve().parent.parent / "webapp" / "static" / "img"

_CDN = "https://d8j0ntlcm91z4.cloudfront.net/user_3G2THIaqFMEKEfdY5lQg4VK5iBT"

# Имя файла → откуда взять. Имена используются в CSS, менять их нельзя.
ARTWORK: dict[str, str] = {
    # портрет анфас, шапка «Сегодня»
    "hero.png": f"{_CDN}/hf_20260904_122511_42ef8f97-a0a3-4309-b45d-68ecbc1edf46.png",
    # гепард у арки, экран «Мой мир»
    "world.png": f"{_CDN}/hf_20260904_122511_c6d26286-18ec-40f9-89a9-1d7d3d86292f.png",
    # профиль, фон окна «Что происходит»
    "moment.png": f"{_CDN}/hf_20260904_122511_fddc3628-f8d7-420e-9dc3-9aff5f21f02e.png",
    # гепард под звёздами, шапка «Прогресса»
    "sky.png": f"{_CDN}/hf_20260904_122511_d57ed7c2-8d43-4d59-932f-3455abf64a21.png",
    # гепард у стола с фруктами, шапка «Еды»
    "food.png": f"{_CDN}/hf_20260907_073653_5fe270f3-1347-4e99-a532-c0e75f25e44b.png",
    # гепард в беге, шапка «Спорта». Кадр горизонтальный, а не портретный,
    # как у остальных: шапка «Спорта» — узкая полоса, и в неё от высокого
    # кадра попадала только верхушка, то есть пустое небо над зверем.
    "gym.png": f"{_CDN}/hf_20260907_100719_81520f48-c7b2-4c93-9515-2878fb2dad71.png",
}

# Файл меньше этого — не картинка, а страница с ошибкой от CDN.
MIN_BYTES = 20_000
TIMEOUT_SECONDS = 180

# Рядом с картинками лежит записка: какая из какой ссылки скачана. Без неё
# замена арта в коде ничего не меняла на сервере — файл-то на месте, и
# проверка «чего не хватает» была довольна. Картинка молча оставалась старой,
# и понять это можно было только глазами.
MANIFEST = ".sources.json"


def _recorded(folder: Path) -> dict[str, str]:
    """Из какой ссылки скачан каждый файл, что лежит на диске."""
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _remember(folder: Path, name: str, url: str) -> None:
    """Запомнить, откуда взялся файл. Не вышло — не беда: в следующий раз
    просто скачаем заново."""
    data = _recorded(folder)
    data[name] = url
    try:
        (folder / MANIFEST).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as error:
        logger.warning("Не записал, откуда взят арт %s: %s", name, error)


def missing(directory: Path | None = None) -> list[str]:
    """Каких артов не хватает на диске — и какие устарели.

    Устаревший — это файл, который лежит на месте, но скачан не из той
    ссылки, что стоит в коде сейчас. Для нас он такой же отсутствующий:
    показывать его нельзя.
    """
    folder = directory or ART_DIR
    known = _recorded(folder)
    absent = []
    for name, url in ARTWORK.items():
        path = folder / name
        if not path.exists() or path.stat().st_size < MIN_BYTES:
            absent.append(name)
        elif known.get(name) != url:
            absent.append(name)
    return absent


async def _download(session: aiohttp.ClientSession, name: str, url: str, folder: Path) -> bool:
    """Скачать один арт. Пишем через временный файл: недокачанный арт
    не должен подменить собой рабочий."""
    target = folder / name
    partial = folder / f"{name}.part"
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            body = await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("Не скачался арт %s: %s", name, e)
        return False

    if len(body) < MIN_BYTES:
        logger.warning("Арт %s пришёл слишком маленьким (%d байт) — пропускаю", name, len(body))
        return False

    partial.write_bytes(body)
    partial.replace(target)
    _remember(folder, name, url)
    logger.info("Арт %s скачан (%d КБ)", name, len(body) // 1024)
    return True


async def ensure_artwork(*, force: bool = False, directory: Path | None = None) -> list[str]:
    """Докачать недостающие арты. Возвращает список скачанных файлов."""
    folder = directory or ART_DIR
    folder.mkdir(parents=True, exist_ok=True)

    needed = list(ARTWORK) if force else missing(folder)
    if not needed:
        return []

    logger.info("Скачиваю арты: %s", ", ".join(needed))
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        results = await asyncio.gather(
            *(_download(session, name, ARTWORK[name], folder) for name in needed)
        )

    return [name for name, ok in zip(needed, results) if ok]


if __name__ == "__main__":  # ручной запуск: python -m services.artwork
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    downloaded = asyncio.run(ensure_artwork(force=True))
    print(f"Готово, скачано файлов: {len(downloaded)}")
