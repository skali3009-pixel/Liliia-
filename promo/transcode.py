"""Ролики Аи — в формат, который понимает браузер записи.

Chromium в рабочем контейнере собран без проприетарных кодеков: H.264 он
не декодирует вовсе (`canPlayType` возвращает пустую строку). На живом
телефоне ролики играют, а в записи на их месте застыла бы заставка — и
промо показывало бы неподвижную Аю там, где она двигается.

Поэтому для съёмки готовятся копии в VP8, и подменяются они только в
браузере (`record.py`). Сами ролики в `webapp/static/trainer/` не
трогаются: правило проекта — ставить их как есть, без перекодирования.
"""
import concurrent.futures, pathlib, subprocess

import imageio_ffmpeg

ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
СБОРКА = ЗДЕСЬ / "build"
ИСТОЧНИК = ЗДЕСЬ.parent / "webapp" / "static" / "trainer" / "animations"
ВЫХОД = СБОРКА / "webm"
FF = imageio_ffmpeg.get_ffmpeg_exe()


def один(путь: pathlib.Path) -> bool:
    цель = ВЫХОД / (путь.stem + ".webm")
    if цель.exists() and цель.stat().st_size > 0:
        return True
    р = subprocess.run([FF, "-v", "error", "-y", "-i", str(путь),
                        "-c:v", "libvpx", "-b:v", "1800k",
                        "-deadline", "realtime", "-cpu-used", "4",
                        "-an", str(цель)], capture_output=True)
    return р.returncode == 0


def main() -> None:
    ВЫХОД.mkdir(parents=True, exist_ok=True)
    файлы = sorted(ИСТОЧНИК.glob("*.mp4"))
    print(f"перекодирую {len(файлы)} роликов…")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as пул:
        готово = list(пул.map(один, файлы))
    плохих = [ф.name for ф, ок in zip(файлы, готово) if not ок]
    print(f"готово: {sum(готово)} из {len(файлы)}")
    if плохих:
        print("не перекодировались:", ", ".join(плохих))


if __name__ == "__main__":
    main()
