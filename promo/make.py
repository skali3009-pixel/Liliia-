"""Собрать промо-ролик целиком: одна команда вместо шести.

    python -m promo.make            # из корня проекта
    python make.py                  # из этой папки

Порядок шагов не случаен: ролики Аи нужны до съёмки, подписи и оправа —
до монтажа. Съёмка сама себя проверяет и при испорченном захвате
повторяется: сбой плавающий, и без проверки испорченный ролик доехал бы
до монтажа незамеченным.
"""
import pathlib, subprocess, sys

ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
ПОПЫТОК = 3


def шаг(имя: str, *аргументы: str) -> None:
    print(f"\n=== {имя} ===")
    р = subprocess.run([sys.executable, str(ЗДЕСЬ / имя), *аргументы])
    if р.returncode:
        sys.exit(f"шаг {имя} не прошёл")


def main(ручка: str = "") -> None:
    шаг("transcode.py")
    снято = False
    for попытка in range(1, ПОПЫТОК + 1):
        print(f"\n=== record.py (попытка {попытка} из {ПОПЫТОК}) ===")
        if subprocess.run([sys.executable, str(ЗДЕСЬ / "record.py")]).returncode == 0:
            снято = True
            break
        print("захват испорчен — снимаю заново")
    if not снято:
        sys.exit(f"запись не удалась {ПОПЫТОК} раза подряд")
    шаг("captions.py")
    шаг("frame.py")
    шаг("endcard.py", *([ручка] if ручка else []))
    шаг("assemble.py")
    готово = ЗДЕСЬ / "build" / "AURA_promo_1080x1920.mp4"
    print(f"\nГотово: {готово} ({готово.stat().st_size / 2**20:.1f} МБ)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
