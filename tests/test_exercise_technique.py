"""Как делать упражнение — словами, внутри приложения.

Раньше «как делать» вело на страницу поиска в YouTube: не на подобранный
ролик, а на предложение поискать самому. Человек уходил из приложения в
чужую ленту посреди тренировки.

Здесь проверяется главное: техника написана про то упражнение, которое
есть в каталоге; она не даёт медицинских выводов и не обещает результат;
а пока её нет, человек не остаётся вообще без подсказки.
"""

import re
from pathlib import Path

from seed.exercise_technique import (DEMO_IMAGES, MOVES_BY_NAME, TECHNIQUE,
                                    demo_image, for_name, move_for)
from seed.workout_programs import PROGRAMS


def catalogue_names() -> set[str]:
    return {item[0] for program in PROGRAMS.values()
            for item in program["exercises"]}


def test_the_technique_describes_exercises_that_exist():
    """Опечатка в названии — и техника не найдётся никогда.

    Ключ здесь — название упражнения, а не номер: одно движение
    встречается в разных программах, и техника у него одна. Значит,
    название обязано совпадать с каталогом посимвольно.
    """
    unknown = set(TECHNIQUE) - catalogue_names()
    assert not unknown, unknown


def test_every_exercise_in_the_catalogue_has_a_technique():
    """Ссылки наружу больше нет — значит, пробелов быть не может.

    Раньше упражнение без техники показывало ссылку на поиск в YouTube.
    Теперь не показывает ничего: человек открыл бы упражнение и не нашёл
    ни слова о том, как его делать. Добавили упражнение — напишите к нему
    технику, и этот тест напомнит об этом сразу.
    """
    missing = catalogue_names() - set(TECHNIQUE)
    assert not missing, missing


def test_every_technique_says_what_to_do():
    """Пустая техника хуже отсутствующей: человек открыл и ничего не нашёл."""
    for name, how in TECHNIQUE.items():
        assert len(how.steps) >= 3, name
        for step in how.steps:
            assert step and step[0].isupper(), (name, step)
            assert not step.endswith("."), (name, step)


def test_the_technique_does_not_diagnose_or_promise():
    """Осторожность в формулировках здесь не украшение.

    Неверная подсказка про колени или поясницу — это не «неудобно», это
    травма. И обещать результат от упражнения мы не вправе.
    """
    forbidden = ("вылечит", "лечит", "избавит", "гарантир", "сожжёт жир",
                 "уберёт жир", "похудеешь", "диагноз", "грыж", "остеохондроз")
    for name, how in TECHNIQUE.items():
        text = " ".join(how.steps + how.mistakes).lower()
        for word in forbidden:
            assert word not in text, (name, word)


def test_the_mistakes_say_what_to_do_instead():
    """«Ты делаешь неправильно» без продолжения — это упрёк, а не помощь."""
    for name, how in TECHNIQUE.items():
        for mistake in how.mistakes:
            assert re.search(r"[—:]", mistake), (name, mistake)


def test_where_there_is_no_technique_yet_nothing_is_invented():
    assert for_name("Такого упражнения нет") is None


# --- показ движения --------------------------------------------------------


def drawn_moves() -> set[str]:
    """Движения, которые приложение умеет рисовать."""
    app = (Path(__file__).resolve().parents[1] / "webapp" / "static"
           / "app.js").read_text(encoding="utf-8")
    body = app.split("const MOVES = {", 1)[1].split("\n};", 1)[0]
    codes = {row.split(":", 1)[0].strip() for row in body.split("\n")
             if ":" in row and row.strip() and not row.strip().startswith("//")}
    return {code for code in codes if code.isalpha()} | {"head", "eyes"}


def test_every_exercise_has_a_movement_to_show():
    """Упражнение без показа — это пустое место посреди подхода.

    Картинок нет почти ни у кого, и появятся они не скоро; движение
    рисуется на месте, и вот оно должно быть у всех.
    """
    missing = catalogue_names() - set(MOVES_BY_NAME)
    assert not missing, missing


def test_the_movements_are_ones_the_app_can_draw():
    """Опечатка в коде движения — пустой кадр, и никто не заметит."""
    unknown = set(MOVES_BY_NAME.values()) - drawn_moves()
    assert not unknown, unknown


def test_the_movement_matches_what_the_exercise_actually_is():
    """Неправильно показанное движение учит неправильному движению.

    Проверяются самые узнаваемые случаи: присед приседает, планка стоит,
    мостик поднимает таз, а упражнения для глаз показывают глаз, а не
    фигуру целиком.
    """
    expected = {
        "Приседания с собственным весом": "squat",
        "Приседания со штангой": "squat",
        "Выпады назад поочерёдно": "lunge",
        "Отжимания с колен": "pushup",
        "Планка на локтях": "plank",
        "Ягодичный мостик": "bridge",
        "Румынская тяга с гантелями": "hinge",
        "Подъёмы ног лёжа": "legraise",
        "Супермен лёжа": "superman",
        "Частое моргание": "eyes",
        "Втягивание подбородка (chin tuck)": "head",
        "Диафрагмальное дыхание лёжа": "breath",
    }
    for name, code in expected.items():
        assert move_for(name) == code, (name, move_for(name))


def test_the_demo_registry_names_exercises_that_exist():
    """Файл, привязанный к несуществующему названию, не покажется никогда."""
    unknown = set(DEMO_IMAGES) - catalogue_names()
    assert not unknown, unknown


def test_without_a_file_no_address_is_invented():
    """Пока анимации нет, адреса нет тоже.

    Выдуманный адрес дал бы битую картинку — это хуже, чем честное пустое
    место: человек решит, что сломалось приложение.
    """
    assert demo_image("Приседания с собственным весом") is None
    assert DEMO_IMAGES == {}, "появились файлы — проверь, что они скачиваются"


def test_a_registered_file_gets_an_address_under_static():
    """Когда файл появится, адрес должен вести в ту же папку, что и остальные
    картинки: их скачивает и раздаёт уже написанный код."""
    DEMO_IMAGES["Планка на локтях"] = "plank.webp"
    try:
        assert demo_image("Планка на локтях") == "/static/img/ex/plank.webp"
    finally:
        DEMO_IMAGES.pop("Планка на локтях")
