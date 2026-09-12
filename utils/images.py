"""Сжатие фотографий перед хранением и отправкой в модель.

Телефон снимает кадр на 3–5 МБ. Для распознавания еды и для сравнения
«до/после» на экране телефона такое разрешение избыточно, а платим мы за
него дважды: местом на диске и токенами картинки в запросе к модели
(их примерно ширина × высота / 750).

Если что-то пойдёт не так, возвращаем исходные байты: лучше отправить
большое фото, чем не отправить никакого.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# Для распознавания еды: дальше уменьшать — начинают теряться детали блюда.
FOOD_MAX_SIDE = 1024
FOOD_QUALITY = 85

# Для фото прогресса: этого хватает и на экране телефона, и на сравнении.
PROGRESS_MAX_SIDE = 1600
PROGRESS_QUALITY = 88


def shrink(data: bytes, *, max_side: int, quality: int) -> bytes:
    """Уменьшить фото до `max_side` по длинной стороне и пережать в JPEG."""
    if not data:
        return data

    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover — на сервере Pillow стоит
        logger.warning("Pillow не установлен — фото не сжимается")
        return data

    try:
        with Image.open(io.BytesIO(data)) as image:
            # Поворот по EXIF: снятое боком фото иначе уедет на бок.
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")

            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side), Image.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
    except Exception:  # noqa: BLE001 — битый файл не повод терять запись
        logger.warning("Не удалось сжать фото, отправляю как есть", exc_info=True)
        return data

    shrunk = buffer.getvalue()
    # Пережатие иногда даёт файл больше исходного (уже сжатый маленький JPEG).
    return shrunk if len(shrunk) < len(data) else data


def for_food(data: bytes) -> bytes:
    """Фото блюда перед отправкой в модель."""
    return shrink(data, max_side=FOOD_MAX_SIDE, quality=FOOD_QUALITY)


def for_progress(data: bytes) -> bytes:
    """Фото прогресса перед сохранением на диск."""
    return shrink(data, max_side=PROGRESS_MAX_SIDE, quality=PROGRESS_QUALITY)


__all__ = ["FOOD_MAX_SIDE", "PROGRESS_MAX_SIDE", "for_food", "for_progress", "shrink"]
