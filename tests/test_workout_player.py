"""Проводник по тренировке.

Каталог отвечает на вопрос «что делать», проводник — «что делать прямо
сейчас». Проверять его отсюда можно только по коду: в браузере он
проверен отдельно, вручную, на живом сервере — и там же поймана ошибка,
из-за которой «Продолжить тренировку» молча не открывало экран.

Здесь заперты те правила, которые легко сломать незаметно: что сделанное
не теряется, что упражнение на время и упражнение на повторы ведут себя
по-разному, и что итог уходит тем же путём, что и раньше.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "webapp" / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STYLES = (STATIC / "styles.css").read_text(encoding="utf-8")


def block(name: str) -> str:
    """Тело функции целиком — до её закрывающей скобки.

    Срез фиксированной длины однажды перелез в соседнюю функцию, и
    проверка «здесь есть try/catch» прошла на коде, где его не было.
    Границу надо брать у самой функции, а не отмерять на глаз.
    """
    return APP_JS.split(name, 1)[1].split("\n}", 1)[0]


def test_the_player_screen_exists_for_every_id_the_code_wires():
    """Опечатка в id ломает проводник молча — посреди тренировки."""
    for element_id in ("player", "player-step", "player-phase", "player-name",
                       "player-set", "player-ring", "player-time", "player-fill",
                       "player-main", "player-pause", "player-skip",
                       "player-sound", "player-close", "player-done-bar",
                       "player-finish", "finish-time", "finish-facts"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id


def test_two_kinds_of_exercise_behave_differently():
    """Планку держат по секундам, приседания считают повторами.

    Это не оформление: у первого подход заканчивается сам, у второго —
    когда человек скажет «готово». Перепутать значит либо торопить, либо
    оставить экран стоять навсегда.
    """
    body = block("function runPlayerTimer(")
    assert "player.phase === 'exercise' && current().seconds" in body

    render = block("function renderPlayer(")
    assert "timed ? `${item.seconds} с` : `${item.reps} повторов`" in render


def test_what_was_done_is_written_down_even_on_early_exit():
    """Выйти посреди тренировки — обычное дело.

    Потерять при этом четыре сделанных подхода — худшее, что может
    случиться: человек их правда сделал.
    """
    body = block("async function leavePlayer(")
    assert "player.done.length === 0" in body
    assert "finishPlayer()" in body
    assert "askYes({" in body, "молча не записываем и молча не выбрасываем"


def test_the_result_goes_the_same_way_as_before():
    """Кристаллы, серия и задания пересчитываются сами.

    Отдельная запись из проводника завела бы вторую систему учёта — и они
    разошлись бы в первый же день.
    """
    body = block("async function finishPlayer(")
    assert "'/api/workouts/log'" in body
    assert "exercise_ids: done" in body
    assert "refresh()" in body


def test_an_interrupted_workout_is_kept_and_offered_back():
    """Мини-приложение закрывается легко: свернул Telegram, позвонили."""
    assert "PLAYER_KEY = 'aura.workout'" in APP_JS
    save = block("function playerSave(")
    assert "localStorage.setItem(PLAYER_KEY" in save

    offer = block("async function offerResume(")
    assert "RESUME_HOURS" in offer, "через полдня это уже другая тренировка"
    assert "openPlayer([], saved)" in offer

    # Проводник обязан открываться и без списка: он лежит в сохранённом.
    # Проверка «список пуст — выходим» без этой оговорки молча не
    # открывала экран, и поймано это было только в браузере.
    opens = block("function openPlayer(")
    assert "if (!saved && !exercises.length) return;" in opens


def test_the_workout_is_forgotten_once_it_is_finished():
    """Иначе назавтра приложение предложит продолжить то, что уже записано."""
    assert "playerForget()" in block("async function finishPlayer(")


def test_the_screen_is_asked_to_stay_awake_but_not_demanded():
    """Гаснущий экран посреди планки — это конец подхода.

    Но умеют это не все телефоны и не все версии Telegram, и падать из-за
    этого нельзя.
    """
    body = block("async function keepAwake(")
    assert "navigator.wakeLock?.request" in body
    assert "catch" in body


def test_sound_can_be_switched_off_and_is_remembered():
    """Тренируются и там, где звук неуместен."""
    assert "MUTE_KEY" in APP_JS
    body = block("function playerMute(")
    assert "localStorage.setItem(MUTE_KEY" in body
    assert "player.muted" in block("function beep(")


def test_the_countdown_ring_does_not_animate():
    """Кольцо перерисовывается раз в секунду.

    Плавность врала бы на последней секунде и мешала бы тем, кто движение
    выключил в настройках телефона.
    """
    assert ".ring-fill.plain" in STYLES
    rule = STYLES.split(".ring-fill.plain", 1)[1][:120]
    assert "transition: none" in rule
