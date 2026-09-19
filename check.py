"""Контролёр постов: проверяет текст по правилам голоса SCALIA.

ЧТО ОН УМЕЕТ: ловить механические огрехи — запрещённые обороты, цепочки
эмодзи, слабые просьбы, длину, отсутствие короткого самостоятельного
высказывания.

ЧЕГО ОН НЕ УМЕЕТ, и это проверено: предсказывать пересылки. Прогнал шесть
её реальных постов с известными цифрами — от 59 пересылок до нуля. По
структуре они не различаются. Пост «Я жива» содержит безупречную строку
«Пусть бушует океан — внутри меня тишина» и собрал одну пересылку.

Разница не в форме, а в том, ПРО КОГО строка:

  «Она не сломалась. Она разархивировалась.»          36 — про любую женщину
  «Настоящая любовь — быть рядом, но не жить вместо»  59 — про отношения читателя
  «Пусть бушует океан — внутри меня тишина»            1 — про автора

Пересылают то, что про жизнь читателя. Это решает человек, не скрипт.
Контролёр — нижняя планка, а не гарантия.

Запуск:  python3 check.py файл.md
         python3 check.py  (читает stdin)
"""

import re
import sys

FORBIDDEN = [
    "вложила душу", "найдёт отклик", "найдет отклик", "очень личное",
    "премьера", "дорогие мои", "проявляться", "трансформироваться",
    "энергия", "дорогие подписчики", "от всего сердца", "с любовью к вам",
]

# Просьба «слушайте на площадках» — не просьба: выполнять нечего.
WEAK_ASKS = ["слушайте на всех", "переходите по ссылке", "ссылка в шапке",
             "ставьте лайк", "подписывайтесь"]

EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]"
)


def check(text: str) -> list[tuple[str, str]]:
    """Возвращает список (уровень, сообщение). Уровень: 'стоп' или 'глянь'."""
    problems = []
    low = text.lower()

    for word in FORBIDDEN:
        if word in low:
            problems.append(("стоп", f"запрещённый оборот: «{word}»"))

    for phrase in WEAK_ASKS:
        if phrase in low:
            problems.append(("глянь", f"слабая просьба: «{phrase}» — "
                                      "человеку нечего выполнить"))

    # Цепочки эмодзи: два и более подряд.
    if re.search(EMOJI.pattern + r"\s*" + EMOJI.pattern, text):
        problems.append(("стоп", "цепочка эмодзи — разрешён один"))

    total_emoji = len(EMOJI.findall(text))
    if total_emoji > 1:
        problems.append(("глянь", f"эмодзи в тексте: {total_emoji}, "
                                  "по правилу максимум один"))

    if "!!" in text:
        problems.append(("стоп", "восклицательные знаки подряд"))

    tags = re.findall(r"#\S+", text)
    if not tags:
        problems.append(("глянь", "нет хэштегов"))
    elif len(tags) > 7:
        problems.append(("глянь", f"хэштегов {len(tags)}, по правилу 5–7"))

    # Пересылаемая строка: две короткие строки подряд, обе короче 90 символов,
    # стоящие отдельным абзацем.
    # Пересылаемая строка — короткое самостоятельное высказывание отдельным
    # абзацем, которое человек отправит вместо своих слов. Одна фраза или две:
    # у её лучшего поста (59 пересылок) она одна, у следующих двух — две.
    # Сначала было условие «ровно две строки» — оно забраковало лучший пост.
    found = False
    for block in text.split("\n\n"):
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if not lines or len(lines) > 2:
            continue
        joined = " ".join(lines)
        if len(joined) > 160:
            continue
        if joined.startswith(("#", "**", ">")) or joined.endswith("?"):
            continue          # хэштеги, заголовки и просьбы — не она
        low_j = joined.lower()
        if "scalia" in low_j or "музыкальных площадк" in low_j:
            continue          # подпись песни тоже коротка, но это не она
        found = True
        break

    if not found:
        problems.append(("стоп", "нет короткого самостоятельного высказывания "
                                "отдельным абзацем"))
    else:
        problems.append(("глянь", "высказывание есть — проверь глазами: оно "
                                  "про жизнь читателя или про твою? "
                                  "Пересылают первое"))

    # Песня подписью в конце.
    if "SCALIA" not in text:
        problems.append(("глянь", "нет строки с названием песни"))

    body = re.sub(r"#\S+", "", text).strip()
    if len(body) > 2200:
        problems.append(("глянь", f"{len(body)} знаков — Instagram режет "
                                  "подпись на 2200"))
    return problems


def main() -> int:
    if len(sys.argv) > 1:
        text = open(sys.argv[1], encoding="utf-8").read()
    else:
        text = sys.stdin.read()

    # В файле может лежать несколько постов в ```-блоках — проверяем каждый.
    blocks = re.findall(r"```\n(.+?)\n```", text, re.S)
    if not blocks:
        blocks = [text]

    bad = 0
    for i, block in enumerate(blocks, 1):
        problems = check(block)
        stops = [p for p in problems if p[0] == "стоп"]
        bad += len(stops)
        mark = "ЧИСТО" if not problems else ("СТОП" if stops else "глянь")
        print(f"\n[{i}] {mark}  ({len(block)} знаков)")
        for level, msg in problems:
            print(f"     {'✗' if level == 'стоп' else '·'} {msg}")
    print(f"\nПроверено блоков: {len(blocks)}. Блокирующих замечаний: {bad}.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
