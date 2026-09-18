"""Скачать кружки Аи по ссылкам от HeyGen и положить туда, где их ждёт бот.

Зачем отдельный скрипт, если качает сам бот. Обычно он и качает: ссылки
лежат в `CIRCLE_SOURCES`, и при старте недостающее докачивается молча. Но
ссылки подписанные и живут около недели — если они протухнут раньше, чем
сервер обновится, кружки надо будет подставить руками. Этот скрипт и есть
тот запасной выход.

    python -m services.fetch_circles hello=<ссылка> ready=<ссылка>

Скачанное проверяется до установки: кружок обязан быть квадратным, короче
минуты и той стороны, которую бот обещает Telegram. Кривой файл до папки не
доходит — лучше остаться без кружка, чем подсунуть телефону то, что он
нарисует обрезанным.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from services.video_notes import CIRCLES_DIR, install, probe


def поставить(имя: str, ссылка: str) -> bool:
    print(f"  качаю {имя}…")
    try:
        with urllib.request.urlopen(ссылка, timeout=120) as ответ:
            data = ответ.read()
    except Exception as ошибка:
        print(f"  ✗ {имя}: не скачалось — {ошибка}")
        return False

    # Проверка и установка — те же, что у бота: двух вариантов «годный
    # файл» в проекте быть не должно.
    беда = install(имя, data)
    if беда:
        print(f"  ✗ {имя}: {беда}")
        return False
    размер, секунды = probe(data)
    print(f"  ✓ {имя}: {размер[0]}×{размер[1]}, "
          f"{секунды:.1f} с, {len(data) / 2**20:.1f} МБ → "
          f"{CIRCLES_DIR / f'{имя}.mp4'}")
    return True


def main(аргументы: list[str]) -> int:
    if not аргументы:
        print(__doc__)
        return 1
    print(f"Кладу кружки в {CIRCLES_DIR}")
    все = True
    for пара in аргументы:
        разобранное = split_pair(пара)
        if разобранное is None:
            print(f"  ✗ не понял «{пара[:40]}…»: нужно имя=ссылка")
            все = False
            continue
        имя, ссылка = разобранное
        все = поставить(имя, ссылка) and все
    print("Готово." if все else "Что-то не встало — смотри строки со знаком ✗.")
    return 0 if все else 1


def split_pair(пара: str) -> tuple[str, str] | None:
    """Разбор «имя=ссылка». Ссылка сама полна знаков «=», поэтому делим один раз."""
    if "=" not in пара:
        return None
    имя, ссылка = пара.split("=", 1)
    return (имя.strip(), ссылка.strip()) if ссылка.startswith("http") else None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
