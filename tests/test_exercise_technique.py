"""Как делать упражнение — словами, внутри приложения.

Раньше «как делать» вело на страницу поиска в YouTube: не на подобранный
ролик, а на предложение поискать самому. Человек уходил из приложения в
чужую ленту посреди тренировки.

Здесь проверяется главное: техника написана про то упражнение, которое
есть в каталоге; она не даёт медицинских выводов и не обещает результат;
а пока её нет, человек не остаётся вообще без подсказки.
"""

import re

from seed.exercise_technique import DEMO_IMAGES, TECHNIQUE, demo_image, for_name
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
