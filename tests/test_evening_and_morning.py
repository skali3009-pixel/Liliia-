"""Итоги дня, утреннее приветствие и письмо вернувшемуся.

Вечернее сообщение — самое опасное из всех: его легко превратить в отчёт,
а отчёт вечером читают уставшими и перестают читать совсем. Поэтому
проверок здесь больше про то, чего в нём не должно быть.
"""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from keyboards.notifications import comeback_keyboard, nudge_keyboard
from models import Base, GenderEnum, GoalEnum, Meal, User, WaterLog
from models.notification import KIND_EVENING, KIND_TURN
from services import evening
from services.context import Action
from services.notifications import (GREETING, MORNING_FROM, MORNING_TO, Prefs,
                                    Sent, decide)


def quest(code, done, hint=""):
    return {"code": code, "title": f"Задание {code}", "icon": "•",
            "done": done, "hint": hint}


# --- итоги дня ------------------------------------------------------------


def test_a_finished_day_is_not_squeezed_for_one_more_action():
    """Главное правило вечера: закрытый день не повод предлагать ещё."""
    done = evening.render([quest("a", True), quest("b", True)])
    assert done.resting
    assert done.target == ""                  # кнопки действия не будет
    assert "достаточно" in done.text or "сложился" in done.text or "закрыт" in done.text


def test_the_resting_message_really_gets_no_action_button(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.test/app")
    done = evening.render([quest("a", True)])
    markup = nudge_keyboard(target=done.target, cta="Посмотреть день",
                            kind=KIND_EVENING)
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert labels == ["Позже", "Сегодня не надо"]


def test_an_unfinished_day_shows_what_is_left_and_asks_gently():
    left = evening.render([quest("a", True), quest("b", False, "1,2 из 2,0 л")])
    assert not left.resting
    assert "✓" in left.text and "○" in left.text
    assert "1,2 из 2,0 л" in left.text        # видно, сколько осталось
    assert "?" in left.text                   # предложение, а не требование


def test_a_day_with_nothing_done_gets_no_checklist():
    """Четыре кружка подряд — это перечень упрёков, а не итоги."""
    assert evening.render([quest("a", False), quest("b", False)]) is None


def test_the_summary_never_turns_into_a_report():
    """Заданий восемь, а строк в сообщении — не больше четырёх.

    Число здесь написано прямо, а не взято из настройки: сравнивать длину
    с той же величиной, которая её задаёт, — значит проверять, что код
    равен самому себе. Такой сторож молча уезжает вместе с ошибкой.
    """
    many = [quest(str(i), i < 4, "подсказка") for i in range(8)]
    text = evening.render(many).text
    lines = [line for line in text.splitlines() if line.startswith(("✓", "○"))]
    assert len(lines) <= 4


def test_what_is_left_stands_last_so_the_eye_ends_on_it():
    many = [quest("сделано", True), quest("осталось", False, "чуть-чуть")]
    lines = [l for l in evening.render(many).text.splitlines()
             if l.startswith(("✓", "○"))]
    assert lines[0].startswith("✓") and lines[-1].startswith("○")


def test_the_evening_has_more_than_one_way_to_say_it():
    for options in (evening.RESTING, evening.OPENING, evening.CLOSING):
        assert len(options) >= 5
        assert len(set(options)) == len(options)


def test_the_evening_wording_changes_from_day_to_day():
    quests = [quest("a", True), quest("b", False, "мало")]
    said = {evening.render(quests, seed=day).text for day in range(5)}
    assert len(said) > 1


def test_nothing_to_summarise_means_no_message():
    assert evening.render([]) is None


# --- утро -----------------------------------------------------------------


NOW = datetime(2026, 9, 8, 6, 0, tzinfo=timezone.utc)
WATER = Action("water", "Вода", "Стакан?", "+250 мл", "water", score=1.1, amount=250)


def ask(**over):
    args = dict(user_id=1, prefs=Prefs(), local_hour=9, today=[], history=[],
                now=NOW, snoozed=set(), day_seed=3)
    args.update(over)
    return decide(WATER, **args)


def test_the_first_message_of_the_morning_says_hello():
    push = ask(local_hour=MORNING_FROM)
    assert push.greeting in GREETING
    assert push.message.startswith("🐆 ")
    assert push.greeting in push.message
    assert "Твой ход" in push.message


def test_the_greeting_is_not_a_separate_message():
    """Отдельное «доброе утро, посмотри свой ход» потратило бы сообщение
    из дневного бюджета и не изменило бы ничего: человеку всё равно
    пришлось бы открыть приложение, чтобы узнать, что ему предлагают."""
    push = ask(local_hour=MORNING_FROM)
    assert WATER.text in push.message


def test_only_the_first_message_of_the_day_greets():
    already = [Sent(KIND_TURN, "meal", NOW - timedelta(hours=4))]
    assert ask(local_hour=MORNING_TO - 1, today=already).greeting == ""


def test_an_afternoon_message_does_not_say_good_morning():
    assert ask(local_hour=MORNING_TO).greeting == ""
    assert ask(local_hour=15).greeting == ""


def test_the_bot_says_nothing_at_all_before_its_earliest_hour():
    """Тихие часы — это «не буди». А здесь другое: в семь утра ещё ничего
    не успело случиться, и «воды сегодня не отмечено» — не наблюдение, а
    будильник по расписанию. Замерено: без этого предела сообщение уходило
    ровно в 07:00 каждый день."""
    from services.notifications import EARLIEST_HOUR

    assert ask(local_hour=EARLIEST_HOUR - 1) is None
    assert ask(local_hour=EARLIEST_HOUR) is not None


def test_the_greeting_changes_from_day_to_day():
    said = {ask(local_hour=MORNING_FROM, day_seed=day).greeting
            for day in range(5)}
    assert len(said) > 1


# --- возвращение ----------------------------------------------------------


def test_the_comeback_letter_offers_one_button_and_no_list(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.test/app")
    markup = comeback_keyboard()
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == 1
    assert buttons[0].text == "Продолжить"
    # На «Сегодня», а не в список накопившихся целей: после перерыва нужен
    # один маленький шаг, а не отчёт о пропущенном.
    assert buttons[0].web_app.url.endswith("screen=today")


def test_without_an_app_the_comeback_letter_still_goes_out(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "")
    assert comeback_keyboard() is None


def test_the_comeback_letters_still_carry_no_numbers_about_the_body():
    """Гарантия из services/comeback.py, которую легко потерять при правке."""
    from services import comeback

    for days in (comeback.AWAY_FIRST, comeback.AWAY_SECOND):
        for started in (True, False):
            text = comeback.render(days, started=started, zones_open=4)
            for word in ("кг", "ккал", "калор", "вес"):
                assert word not in text.lower(), text
