"""Интерфейс для любого профиля: мужского, женского и без указанного пола.

Тестовый профиль был мужской — и видел «Съела это», «Я занималась сама»,
«Насколько голодна?», женский силуэт в «Твоём теле» и раздел «Женское» в
подборе тренировок. Здесь две разные гарантии.

1. Там, где пол для дела не нужен, обращение нейтральное. Сторож смотрит на
   то, что человек читает (строки кода и текст страницы), а не на
   комментарии: в комментариях эти слова стоят по делу, ими правило и
   объясняется.
2. То, что относится к одному полу, видно только тому, кто сам указал этот
   пол в анкете. Не угадывается по имени — пол берётся только из анкеты.
   Проверяется поведением, настоящими запросами, для трёх профилей.

Голос самого бота («Записала», «Передала») — это голос персонажа, а не
обращение к человеку, и здесь не проверяется.
"""

import asyncio
import io
import pathlib
import re
import tokenize

import pytest

from models import GenderEnum, GoalEnum, User
from tests.test_webapp_api import USER_ID, call, maker_holder, webapp_client

# Формы, которые говорят с человеком в женском роде. Список закрытый: слово
# сюда добавляют, когда находят новое обращение, а не на всякий случай.
FEMININE = (
    "съела", "занималась", "голодна", "передумала", "пользовалась", "привела",
    "остановилась", "дошла", "прошла", "записывала", "открыла", "сорвалась",
    "пропустила", "хотела", "пришла", "увидела", "нажала", "ожидала", "мерила",
    "позавтракала", "выпила", "бегала", "плавала", "танцевала", "ходила",
    "делала", "собрана", "оформила", "завела",
)
PATTERN = re.compile(r"(?<![а-яё])(" + "|".join(FEMININE) + r")(?![а-яё])", re.I)

# Файлы, где женский род законен: юридический текст Лилия менять не
# велела, календарь виден только женщинам, журнал (logger) человек не читает.
ALLOWED_FILES = {"handlers/legal.py", "services/cycle.py"}
ALLOWED_LINES = (
    "logger.",                 # журнал сервера
    "Вся команда уже собрана",  # «команда» — это сам ярлык на айфоне
    "Отметь день, когда начались месячные",   # тур календаря — только женщинам
)


def _python_strings(path: pathlib.Path):
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.STRING or token.string.startswith(('"""', "'''")):
            continue
        line = lines[token.start[0] - 1]
        yield token.start[0], token.string, line


def _visible_python():
    for folder in ("handlers", "services", "keyboards", "utils"):
        for path in sorted(pathlib.Path(folder).glob("*.py")):
            if str(path) in ALLOWED_FILES:
                continue
            for number, text, line in _python_strings(path):
                if any(mark in line for mark in ALLOWED_LINES):
                    continue
                yield f"{path}:{number}", text


def _visible_js():
    source = pathlib.Path("webapp/static/app.js").read_text(encoding="utf-8")
    for number, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        if any(mark in line for mark in ALLOWED_LINES):
            continue
        for _, text in re.findall(r"(['`])((?:(?!\1).)*)\1", line):
            yield f"app.js:{number}", text


def _visible_html():
    page = pathlib.Path("webapp/static/index.html").read_text(encoding="utf-8")
    page = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), page, flags=re.S)
    for number, line in enumerate(page.splitlines(), 1):
        yield f"index.html:{number}", line


def test_nobody_is_addressed_as_a_woman_where_gender_does_not_matter():
    found = [f"{where}: {PATTERN.search(text).group(0)}"
             for source in (_visible_python(), _visible_js(), _visible_html())
             for where, text in source if PATTERN.search(text)]
    assert not found, "\n".join(found)


def test_the_guard_sees_what_it_is_meant_to_see():
    """Сторож проверен на деле: строка с обращением ловится, комментарий — нет."""
    assert PATTERN.search("Передумала — нажми любую кнопку меню.")
    assert PATTERN.search("Насколько голодна?")
    assert not PATTERN.search("Насколько хочется есть?")


# --- Поведение для трёх профилей ------------------------------------------

async def _set_gender(gender):
    async with maker_holder["maker"]() as session:
        user = await session.get(User, USER_ID)
        user.gender = gender
        await session.commit()


@pytest.mark.parametrize("gender,sees", [
    (GenderEnum.FEMALE, True), (GenderEnum.MALE, False), (None, False)],
    ids=["женский", "мужской", "не указан"])
def test_female_only_parts_follow_the_questionnaire(gender, sees):
    async def scenario():
        async with webapp_client() as (client, _):
            await _set_gender(gender)

            gym = await (await call(client, "GET", "/api/workouts")).json()
            codes = [item["code"] for item in gym["categories"]]
            assert ("women" in codes) is sees
            # Остальные направления видны всем одинаково.
            assert {"body", "calm", "face", "posture", "eyes"} <= set(codes)

            progress = await (await call(client, "GET", "/api/progress")).json()
            assert progress["body"]["figure"] is sees
            # Замеры и выводы от пола не зависят — они есть у всех.
            assert "zones" in progress["body"] and "insights" in progress["body"]
            assert (progress.get("cycle") is not None) is sees
    run(scenario)


def test_a_direct_link_to_the_section_still_opens_it():
    """Чип спрятан, но дверь не заперта: пришедший по ссылке раздел видит."""
    async def scenario():
        async with webapp_client() as (client, _):
            await _set_gender(GenderEnum.MALE)
            gym = await (await call(client, "GET", "/api/workouts?category=women")).json()
            assert "women" in [item["code"] for item in gym["categories"]]
            assert gym["programs"]
    run(scenario)


def test_the_picker_never_suggests_a_private_topic():
    """«Что сделать сейчас» не предлагает тазовое дно главной карточкой —
    никому: это разговор о теле, которого человек не начинал."""
    from services.workout_picker import pick

    for minutes in (5, 15, 30, 45, 60):
        for energy in (None, 1, 5):
            picks = pick(minutes_available=minutes, energy=energy, limit=10)
            assert all(item.category != "women" for item in picks)
    # По прямому выбору направления — можно.
    assert pick(minutes_available=45, category="women")


def test_the_mood_is_stored_as_before_and_shown_neutrally():
    """«устала» остаётся в базе — так записано у всех, кто отмечал раньше;
    на экране и в ленте — «устало»."""
    from services.moments import MOODS, mood_word

    assert "устала" in MOODS
    assert mood_word("устала") == "устало"
    assert mood_word("бодро") == "бодро"
    app = pathlib.Path("webapp/static/app.js").read_text(encoding="utf-8")
    assert "const MOOD_SHOWN = { 'устала': 'устало' };" in app


def test_old_button_data_is_untouched():
    """Тексты менялись, данные кнопок — нет: старые сообщения в чате
    продолжают работать."""
    from handlers import errors, suggestions

    assert suggestions.CB_EAT == "eat:"
    assert errors.CB_TELL


# --- Цель и вес цели --------------------------------------------------------

@pytest.mark.parametrize("goal,weight,target,conflict", [
    (GoalEnum.GAIN_MASS, 69, 67, True),       # случай из записи
    (GoalEnum.GAIN_MASS, 69, 73, False),
    (GoalEnum.LOSE_WEIGHT, 69, 73, True),
    (GoalEnum.LOSE_WEIGHT, 69, 67, False),
    (GoalEnum.MAINTAIN, 69, 67, False),
    (GoalEnum.RECOMPOSITION, 69, 67, False),
    (GoalEnum.GAIN_MASS, 69, 68.7, False),    # полкило — это весы, не цель
    (GoalEnum.GAIN_MASS, 69, None, False),
])
def test_goal_and_target_that_disagree_are_named(goal, weight, target, conflict):
    from services.profile import goal_conflict

    user = User(goal=goal, current_weight_kg=weight, target_weight_kg=target)
    assert bool(goal_conflict(user)) is conflict


def test_the_conflict_is_named_but_the_goal_is_not_changed():
    """Решать за человека нельзя: цель остаётся, пока он сам её не сменит."""
    async def scenario():
        async with webapp_client() as (client, _):
            async with maker_holder["maker"]() as session:
                user = await session.get(User, USER_ID)
                user.goal, user.current_weight_kg = GoalEnum.GAIN_MASS, 69
                await session.commit()
            response = await call(client, "PATCH", "/api/profile",
                                  json_body={"target_weight": 67})
            data = await response.json()
            assert "набор массы" in data["profile"]["goal_conflict"]
            assert data["profile"]["goal"] == "gain_mass"

            from handlers.profile import profile_text

            async with maker_holder["maker"]() as session:
                user = await session.get(User, USER_ID)
                assert "⚠️ Цель — набор массы" in profile_text(user)
                assert user.goal == GoalEnum.GAIN_MASS
    run(scenario)


def run(scenario):
    asyncio.run(scenario())
