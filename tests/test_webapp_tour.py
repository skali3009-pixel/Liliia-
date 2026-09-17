"""Подсказки по кнопкам.

Анкета в чате спрашивает рост и цель, а что делать на пяти вкладках, не
говорит никто: человек попадает на «Сегодня», видит десяток блоков и
закрывает приложение. Здесь заперто то, что ломается молча — подсветка
пустого места, подсказка поверх открытого окна, забытая отметка «уже
показывали» и движение мимо настройки «уменьшить движение».
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "webapp" / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STYLES = (STATIC / "styles.css").read_text(encoding="utf-8")

ЭКРАНЫ = ("today", "world", "gym", "cube", "progress")


def тур() -> str:
    """Определение подсказок — от TOUR до закрывающей скобки."""
    return APP_JS.split("const TOUR = {", 1)[1].split("\n};", 1)[0]


def шаги() -> list[dict]:
    """Шаги подсказок, разобранные из кода: экран, селектор, заголовок."""
    собрано = []
    экран = None
    for строка in тур().splitlines():
        начало = re.match(r"\s{2}(\w+): \[", строка)
        if начало:
            экран = начало.group(1)
            continue
        шаг = re.search(r"sel: '([^']+)'", строка)
        if шаг:
            собрано.append({"экран": экран, "sel": шаг.group(1),
                            "card": "card: true" in строка})
    return собрано


def test_every_tab_explains_itself():
    """Всё сразу на «Сегодня» — это двадцать карточек про то, чего человек
    ещё не видел. Поэтому у каждой вкладки свой короткий тур."""
    есть = {ш["экран"] for ш in шаги()}
    assert есть == set(ЭКРАНЫ), есть ^ set(ЭКРАНЫ)
    for экран in ЭКРАНЫ:
        сколько = sum(1 for ш in шаги() if ш["экран"] == экран)
        assert 2 <= сколько <= 5, (экран, сколько)


def test_the_tour_starts_on_the_first_visit_of_each_tab():
    """Иначе подсказки увидит только тот, кто открыл приложение впервые."""
    тело = APP_JS.split("function switchScreen(", 1)[1].split("\n}", 1)[0]
    assert "maybeTour(name);" in тело
    # И на «Сегодня» — после первой отрисовки, а не до неё: до этого половины
    # блоков на экране ещё нет.
    запуск = APP_JS.split("playEntrance('today');", 1)[1][:200]
    assert "maybeTour('today');" in запуск


def test_a_block_that_is_not_on_screen_is_never_pointed_at():
    """Женский календарь виден не всем, «Твой ход» бывает пустым.

    Подсветить пустое место хуже, чем промолчать: человек ищет глазами то,
    чего нет, и решает, что приложение сломалось.
    """
    цель = APP_JS.split("function tourTarget(", 1)[1].split("\n}", 1)[0]
    assert "if (!found) return null;" in цель
    assert "box.hidden || box.offsetParent === null" in цель
    # Шаги просеиваются до показа, иначе счётчик «3 из 5» соврёт.
    старт = APP_JS.split("function startTour(", 1)[1].split("\n}", 1)[0]
    assert "filter((step) => tourTarget(step))" in старт
    assert "if (tourSteps.length === 0)" in старт


def test_the_tour_never_covers_what_it_points_at():
    """Подсказка поверх подсвеченного блока читается как ошибка отрисовки.

    Высота окошка обрезается по свободной полосе — всему, что выше карточки.
    Поймано в браузере: кольцо калорий и задания дня карточка накрывала.
    """
    шаг = APP_JS.split("function showTourStep(", 1)[1].split("\n}", 1)[0]
    assert "полоса" in шаг and "card.offsetHeight" in шаг
    assert "Math.min(rect.height + pad * 2, полоса.низ" in шаг
    # Прокрутка мгновенная: плавная кончается позже, чем мы меряем.
    assert "behavior: 'auto'" in шаг
    assert "behavior: 'smooth'" not in шаг


def test_the_tour_does_not_barge_into_an_open_sheet():
    """Человек сейчас занят другим — подсказка подождёт."""
    старт = APP_JS.split("function startTour(", 1)[1].split("\n}", 1)[0]
    assert "document.querySelector('.sheet:not([hidden])')" in старт


def test_what_was_shown_is_remembered_and_can_be_brought_back():
    """Показывать одно и то же при каждом заходе — это навязчивость.

    Но и пролиставший в первый день не должен остаться без объяснений
    навсегда: в профиле есть кнопка.
    """
    assert "const TOUR_KEY = 'aura.tour';" in APP_JS
    for имя in ("function tourSeen(", "function rememberTour(", "function forgetTours("):
        assert имя in APP_JS, имя
    # Приватный режим не должен ронять экран.
    видели = APP_JS.split("function tourSeen(", 1)[1].split("\n}", 1)[0]
    assert "catch" in видели and "new Set()" in видели

    assert 'id="tour-again"' in INDEX
    кнопка = APP_JS.split("getElementById('tour-again').onclick", 1)[1][:300]
    assert "forgetTools" not in кнопка
    assert "forgetTours();" in кнопка
    assert "startTour(" in кнопка


def test_the_tour_speaks_plainly_and_promises_nothing():
    """Те же правила, что и у техники: ни диагнозов, ни обещаний результата."""
    текст = тур().lower()
    for запрет in ("похуде", "вылеч", "гарантирова", "избавит", "сожжёт",
                   "результат за", "обязательно получится"):
        assert запрет not in текст, запрет
    # Каждый шаг — одно предложение о деле, а не абзац.
    for кусок in re.findall(r"text: '([^']+)'", тур()):
        assert len(кусок) <= 190, кусок


def test_the_tour_moves_only_inside_the_motion_setting():
    """Как всё движение в проекте."""
    движение = STYLES.split("Движение\n", 1)[1]
    снаружи = re.split(r"@media \(prefers-reduced-motion[^)]*\)", движение)[0]
    assert "#tour-hole { transition" not in снаружи
    разрешено = движение.split("@media (prefers-reduced-motion: no-preference)", 1)[1]
    assert "#tour-hole { transition: left" in разрешено
    assert "#tour-card { animation: rise" in разрешено
    # Само окошко без движения всё равно работает — оно просто не едет.
    правило = STYLES.split("#tour-hole {", 1)[1].split("}", 1)[0]
    assert "transition" not in правило and "animation" not in правило


def test_the_tour_points_at_blocks_that_exist_in_the_markup():
    """Селектор с опечаткой не упадёт — шаг просто исчезнет, и молча.

    Проверяются те цели, что записаны в разметке; остальные рисует код, и
    их ловит проверка в браузере.
    """
    классы = set()
    for кусок in re.findall(r'class="([^"]+)"', INDEX):
        классы.update(кусок.split())
    иды = set(re.findall(r'id="([^"]+)"', INDEX))

    for шаг in шаги():
        цель = шаг["sel"]
        имя = цель[1:]
        if цель.startswith("#"):
            assert имя in иды, (шаг["экран"], цель)
        else:
            assert имя in классы, (шаг["экран"], цель)


def test_no_browser_dialogs_crept_in_with_the_tour():
    """В приложении нет ни одного системного окошка — и здесь тоже."""
    for запрет in ("prompt(", "confirm(", "alert("):
        assert запрет not in тур(), запрет
