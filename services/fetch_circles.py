"""Скачать кружки Аи по ссылкам от HeyGen и положить туда, где их ждёт бот.

Зачем отдельный скрипт. Ролики делает HeyGen, а забрать их файлом из рабочей
сессии нельзя: прокси не пускает к их хранилищу (403, политика организации).
Зато у сервера интернет открыт — значит, качает он.

Ссылки подписанные и живут около недели, поэтому в код они не вписаны:
передаются аргументами, и в репозитории не остаётся ни одной.

    python -m services.fetch_circles hello=<ссылка> ready=<ссылка>

Скачанное проверяется до установки: кружок обязан быть квадратным, короче
минуты и той стороны, которую бот обещает Telegram. Кривой файл до папки не
доходит — лучше остаться без кружка, чем подсунуть телефону то, что он
нарисует обрезанным.
"""

from __future__ import annotations

import struct
import sys
import urllib.request
from pathlib import Path

from services.video_notes import CIRCLES, CIRCLES_DIR, MAX_SECONDS, SIDE


def разобрать(data: bytes) -> tuple[tuple[int, int] | None, float | None]:
    """Сторона кадра и длительность прямо из MP4, без сторонних программ."""
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


def поставить(имя: str, ссылка: str) -> bool:
    if имя not in CIRCLES:
        print(f"  ✗ {имя}: такого кружка нет. Бывают: {', '.join(CIRCLES)}")
        return False
    print(f"  качаю {имя}…")
    try:
        with urllib.request.urlopen(ссылка, timeout=120) as ответ:
            data = ответ.read()
    except Exception as ошибка:
        print(f"  ✗ {имя}: не скачалось — {ошибка}")
        return False

    размер, секунды = разобрать(data)
    if размер is None:
        print(f"  ✗ {имя}: это не похоже на видео ({len(data)} байт)")
        return False
    if размер[0] != размер[1]:
        print(f"  ✗ {имя}: кадр {размер[0]}×{размер[1]}, а нужен квадрат — "
              "Telegram обрежет всё лишнее")
        return False
    if размер[0] != SIDE:
        print(f"  ✗ {имя}: сторона {размер[0]}, а бот обещает Telegram {SIDE}")
        return False
    if секунды is not None and секунды > MAX_SECONDS:
        print(f"  ✗ {имя}: {секунды:.0f} секунд, а Telegram берёт не больше "
              f"{MAX_SECONDS}")
        return False

    CIRCLES_DIR.mkdir(parents=True, exist_ok=True)
    путь = CIRCLES_DIR / f"{имя}.mp4"
    путь.write_bytes(data)
    print(f"  ✓ {имя}: {размер[0]}×{размер[1]}, "
          f"{секунды:.1f} с, {len(data) / 2**20:.1f} МБ → {путь}")
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
