"""Сколько места осталось на диске.

Фотографии прогресса растут быстрее всего остального. Когда диск кончается,
перестаёт писаться и база — то есть встаёт весь бот. Поэтому за местом
следим заранее и первым делом отключаем приём новых фото, а не запись
дневника.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import config


@dataclass(frozen=True)
class DiskUsage:
    total_gb: float
    used_gb: float
    free_gb: float
    percent: int

    @property
    def warning(self) -> bool:
        return self.percent >= config.DISK_WARN_PERCENT

    @property
    def full(self) -> bool:
        return self.percent >= config.DISK_STOP_PERCENT


def usage(path: str | Path | None = None) -> DiskUsage:
    """Занятость диска там, где лежат фотографии."""
    target = Path(path or config.PHOTOS_DIR)
    while not target.exists() and target != target.parent:
        target = target.parent

    total, used, free = shutil.disk_usage(target)
    gb = 1024 ** 3
    return DiskUsage(
        total_gb=round(total / gb, 1),
        used_gb=round(used / gb, 1),
        free_gb=round(free / gb, 1),
        percent=round(used / total * 100) if total else 0,
    )


def render_warning(disk: DiskUsage) -> str:
    if disk.full:
        return (f"🛑 Диск заполнен на {disk.percent}% — бот перестал принимать новые "
                f"фотографии, чтобы не остановить запись дневника. Свободно "
                f"{disk.free_gb} ГБ из {disk.total_gb}.")
    return (f"⚠️ Диск заполнен на {disk.percent}%. Свободно {disk.free_gb} ГБ из "
            f"{disk.total_gb} — пора расширять или выносить фотографии.")


__all__ = ["DiskUsage", "render_warning", "usage"]
