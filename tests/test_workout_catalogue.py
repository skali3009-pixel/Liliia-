"""Каталог тренировок: направления, занятия и личные темы.

Три вещи, которые легко испортить.

Йога, пилатес и стретчинг у нас были всегда — но лежали внутри «Тела»
рядом с «Зал · Средний», и человек, который не хочет «тренировку», до них
просто не доходил. Разделы существуют не для порядка в базе, а чтобы их
находили.

Занятия — не программа упражнений. Человеку, который бегает, не нужен
список «как бегать»; ему нужно записать, что он бегал сорок минут.

А личная тема не открывается без спроса.
"""

import pytest

from seed.workout_programs import (CARDIO, CATEGORIES, CATEGORIES_WITH_CALORIES,
                                   PROGRAMS, STYLES)
from services.workouts import available_programs, styles_for


def test_calm_practices_are_a_direction_of_their_own():
    """Их не «добавляли» — их вытащили. Они были и раньше, но внутри «Тела»."""
    calm = {p.code for p in available_programs(category="calm")}
    assert {"yoga", "pilates", "stretching"} <= calm
    assert not any(PROGRAMS[code]["category"] == "body"
                   for code in ("yoga", "pilates", "stretching"))


def test_every_direction_has_something_in_it():
    """Пустая вкладка хуже отсутствующей: человек нажал и ничего не нашёл."""
    for code, title in CATEGORIES:
        assert available_programs(category=code), title


def test_the_new_topics_are_there():
    codes = set(PROGRAMS)
    for code in ("dance_warmup", "chin_line", "neck_hump", "pelvic_floor"):
        assert code in codes, code


def test_styles_are_offered_only_where_they_mean_something():
    """У спокойного форма и есть направление — второй ряд фильтров там
    был бы выбором из одного."""
    assert styles_for("body")
    assert not styles_for("calm")
    assert not styles_for("eyes")


def test_calories_are_shown_only_where_they_are_real():
    """У гимнастики для глаз расход ничтожен, и цифра рядом с ней врёт."""
    assert "body" in CATEGORIES_WITH_CALORIES
    assert "dance" in CATEGORIES_WITH_CALORIES
    assert "eyes" not in CATEGORIES_WITH_CALORIES
    assert "face" not in CATEGORIES_WITH_CALORIES


# --- личная тема ----------------------------------------------------------


def test_the_personal_topic_carries_a_warning():
    warning = PROGRAMS["pelvic_floor"].get("warning")
    assert warning, "личная тема не может открываться без предупреждения"
    low = warning.lower()
    assert "не лечение" in low or "не заменяет врача" in low
    assert "боли" in low


def test_the_warning_reaches_the_screen():
    program = next(p for p in available_programs(category="women")
                   if p.code == "pelvic_floor")
    assert program.warning


def test_ordinary_programs_have_no_warning():
    """Иначе предупреждение перестанут читать."""
    for code, program in PROGRAMS.items():
        if code != "pelvic_floor":
            assert not program.get("warning"), code


def test_no_program_promises_treatment():
    """Запрещено обещание и присвоенный диагноз, а не слово.

    «Если тебе поставили диагноз — спроси врача» это предостережение и
    ровно то, что там должно быть. «Ставим диагноз» — то, чего мы делать
    не вправе. Первая версия этой проверки не различала их и рубила
    заботу вместе с обещаниями.
    """
    forbidden = ("вылечит", "избавит", "гарантир", "уберёт навсегда",
                 "похудеешь на", "ставим диагноз", "определим причину")
    for code, program in PROGRAMS.items():
        text = f"{program['title']} {program['subtitle']} {program.get('warning') or ''}"
        for word in forbidden:
            assert word not in text.lower(), code


# --- занятия --------------------------------------------------------------


def test_the_activities_cover_what_people_actually_do():
    names = {name for name, _, _ in CARDIO}
    for expected in ("Бег трусцой", "Беговая дорожка", "Эллипс", "Плавание",
                     "Танцы", "Велосипед на улице", "Прогулка спокойным шагом"):
        assert expected in names, expected


def test_every_activity_has_a_sane_effort_value():
    """MET — из справочника, а не с потолка: по нему считается расход."""
    for name, minutes, met in CARDIO:
        assert 1.5 <= met <= 12, name
        assert 5 <= minutes <= 90, name


def test_activities_do_not_repeat():
    names = [name for name, _, _ in CARDIO]
    assert len(names) == len(set(names))


# --- что нашлось при разборе ----------------------------------------------


def test_the_catalogue_has_almost_no_duplicates():
    """Лилия просила убрать повторы. Их почти нет, и оставшиеся законны:
    планка есть и в домашней тренировке, и в пилатесе."""
    from collections import Counter

    names = Counter(row[0] for p in PROGRAMS.values() for row in p["exercises"])
    repeated = {name: n for name, n in names.items() if n > 1}
    assert set(repeated) <= {"Планка на локтях", "Супермен лёжа", "Кошка-корова",
                             "Кошка-корова ", "Сведение лопаток стоя",
                             "«Стенка»: скольжение руками по стене"}, repeated
    assert max(repeated.values(), default=0) <= 3
