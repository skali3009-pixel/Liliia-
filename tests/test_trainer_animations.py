"""Тренер: готовые анимации персонажа.

Персонажа приложение больше не рисует само. Анимации нарисованы заранее,
лежат в `webapp/static/trainer/` и подключаются как есть.

Всё, что здесь заперто, ломается молча. Опечатка в коде упражнения, файл,
не доехавший до сервера, потерянный кадр — ни одно из этого не бросает
ошибку: человек просто открывает окно и видит пустое место или заставку,
которая никогда не оживёт. Узнали бы мы об этом от Лилии, а не от кода.
"""

import json
import re
from pathlib import Path

from seed.exercise_ids import EXERCISE_IDS, id_for
from seed.workout_programs import PROGRAMS

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "webapp" / "static"
TRAINER = STATIC / "trainer"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STYLES = (STATIC / "styles.css").read_text(encoding="utf-8")
PACK = json.loads((TRAINER / "manifest.json").read_text(encoding="utf-8"))


def catalogue_names() -> set[str]:
    return {item[0] for program in PROGRAMS.values()
            for item in program["exercises"]}


# --- постоянный код упражнения --------------------------------------------


def test_every_exercise_has_a_permanent_code():
    """Название — русская строка, и связывать по ней файлы нельзя.

    Числовой `id` из базы тоже не подходит: он выдаётся при заливке и на
    другом сервере будет другим. Значит, у каждого упражнения каталога
    обязан быть свой постоянный код.
    """
    assert catalogue_names() == set(EXERCISE_IDS)


def test_two_exercises_never_share_one_code():
    """Один код на двоих — это одна анимация на два разных движения."""
    assert len(set(EXERCISE_IDS.values())) == len(EXERCISE_IDS)


def test_the_code_is_written_out_and_not_derived_from_the_name():
    """Транслитерация даёт разные строки на разных версиях библиотеки.

    Связь с файлами порвалась бы без единой ошибки в логах, поэтому коды
    заданы явно и состоят только из латиницы, цифр и подчёркиваний.
    """
    for name, code in EXERCISE_IDS.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), (name, code)


def test_one_exercise_in_several_programs_keeps_one_code():
    """Планка стоит в трёх программах, и анимация у неё одна."""
    assert id_for("Планка на локтях") == "forearm_plank"
    places = [f"{code}#{i}" for code, program in PROGRAMS.items()
              for i, item in enumerate(program["exercises"])
              if item[0] == "Планка на локтях"]
    assert len(places) == 3, places


# --- пакет анимаций --------------------------------------------------------


def test_the_manifest_names_exercises_that_exist():
    """Опечатка в коде — анимация не найдётся никогда и молча."""
    unknown = set(PACK["animations"]) - set(EXERCISE_IDS.values())
    assert not unknown, unknown


def test_every_file_named_in_the_manifest_is_on_disk():
    """Файл, не доехавший до сервера, даёт пустой кадр без единой ошибки."""
    for code, item in PACK["animations"].items():
        for key in ("asset", "poster"):
            assert (TRAINER / item[key]).exists(), (code, item[key])


def test_the_frames_are_where_the_code_looks_for_them():
    """Папку кадров код выводит из имени готового файла.

    Это единственное место, где путь собирается по строке, — значит,
    сверять его надо с диском, а не с самим собой.
    """
    for code, item in PACK["animations"].items():
        stem = item["asset"].split("/")[-1].removesuffix(".webp")
        for number in range(1, item["frames"] + 1):
            frame = TRAINER / "frames" / stem / f"frame_0{number}.png"
            assert frame.exists(), (code, str(frame))
        # Лишних кадров тоже быть не должно: листалка считает по манифесту.
        assert len(list((TRAINER / "frames" / stem).glob("*.png"))) == item["frames"]


def test_the_key_frame_the_still_view_shows_exists_in_every_pack():
    """С выключенным движением показывается кадр 04 — и только он."""
    # Именно четвёртый: на нём движение в нижней точке, по нему упражнение
    # и узнают. Первый кадр — просто «стоит», и показывать его бессмысленно.
    steps = APP_JS.split("function trainerFrames(", 1)[1].split("\n}", 1)[0]
    assert "let at = Math.min(4, count);" in steps
    still = APP_JS.split("function ExerciseTrainerAnimation(", 1)[1].split("\n}", 1)[0]
    assert "if (!motion())" in still
    for code, item in PACK["animations"].items():
        assert item["frames"] >= 4, code


# --- как это подключено ----------------------------------------------------


def test_the_animation_is_found_by_code_and_never_by_name():
    """По русскому названию файлы не ищутся никогда.

    Одна запятая в названии — и человек молча остался бы без показа.
    """
    body = APP_JS.split("function trainerFor(", 1)[1].split("\n}", 1)[0]
    assert "animations?.[exerciseId]" in body
    assert "label" not in body and "name" not in body


def test_the_server_sends_the_code_with_every_exercise():
    api = (ROOT / "webapp" / "api.py").read_text(encoding="utf-8")
    assert '"exercise_id": id_for(workout.name),' in api
    # В проводник код должен доехать тоже: там свой список упражнений.
    assert "exercise_id: item.exercise_id || null," in APP_JS


def test_without_an_asset_nothing_is_drawn_instead():
    """Прежний рисованный персонаж убран из интерфейса.

    Две разные графики в одном экране — это два разных приложения на вид.
    Пока анимации нет, честнее одна строка, чем чужая фигура. Код старого
    персонажа оставлен намеренно, а вот вызовов из интерфейса быть не
    должно — их и проверяем.
    """
    assert APP_JS.count("showMove(") == 1, "показ рисованной фигуры снова вызывается"
    assert "Анимация техники готовится" in INDEX


def test_the_frame_is_square_and_the_character_is_not_cropped():
    """Холст у всех анимаций один, и кадр не должен прыгать между ними.

    Вписываем целиком: обрезать персонажа по краям нельзя — поза важнее
    плотно залитого кадра.
    """
    assert ".how-demo.square { aspect-ratio: 1 / 1; }" in STYLES
    rule = STYLES.split(".trainer-shot {", 1)[1].split("}", 1)[0]
    assert "object-fit: contain" in rule
    # Квадрат включается в обоих местах показа — и в окне техники, и в
    # проводнике. Первая версия проверки крутила цикл по названиям, но
    # искала одну и ту же строку, поэтому прошла бы и на одном.
    assert APP_JS.count("classList.toggle('square'") == 2


def test_the_heavy_file_starts_loading_before_the_window_opens():
    """Файл весит мегабайты. Начать качать его в момент открытия окна —
    значит показать человеку заставку и заставить ждать."""
    assert "link.onpointerdown = () => preloadTrainer(exercise.exercise_id);" in APP_JS
    rest = APP_JS.split("} else if (phase === 'rest') {", 1)[1].split("\n  }", 1)[0]
    assert "preloadTrainer(next.exercise_id)" in rest


def test_the_pack_is_used_as_it_is():
    """Анимации не пересобираются: готовый WebP ставится как есть.

    Разбор на кадры остаётся только запасным путём — для браузеров, где
    анимированный WebP не работает, и для выключенного движения.
    """
    body = APP_JS.split("function ExerciseTrainerAnimation(", 1)[1].split("\n}", 1)[0]
    assert "TRAINER_ROOT + item.asset" in body
    assert "canvas" not in body.lower()
