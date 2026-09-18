"""Что сработало, а что только потратило внимание.

Главная мера здесь одна и она не про количество. Сообщение, которое
открывают и после которого ничего не делают, успешным не считается: оно
израсходовало внимание и ничего не изменило. Поэтому темы сортируются по
доле нажатий, и первой идёт худшая — чинить надо её.
"""

import asyncio
import contextlib
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, GenderEnum, GoalEnum, User
from models.notification import (KIND_MEAL, KIND_WATER, RESULT_ACTED,
                                 RESULT_DISABLED, RESULT_MUTED, RESULT_OPENED,
                                 RESULT_SNOOZED)
from services import notifications
from services.context import VARIANTS, stamp
from services.owner_reports import KIND_RU, _notification_lines
from utils.timeframe import today_in

NOW = datetime.combine(today_in("Europe/Moscow"), time(12, 0), tzinfo=timezone.utc)


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165,
                         current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                         onboarding_completed=True, timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


async def sent(session, kind, result="", *, variant="", ago=1):
    push = notifications.Push(user_id=1, kind=kind, code="x", text="…", cta="…",
                              target="water", variant=variant)
    moment = NOW - timedelta(hours=ago)
    await notifications.remember(session, push, day=moment.date(), now_utc=moment)
    if result:
        await notifications.mark(session, 1, kind, result, now_utc=moment)


# --- подпись формулировки -------------------------------------------------


def test_every_wording_can_be_told_apart_afterwards():
    """Без подписи в истории осталось бы «писали про воду», а какими
    словами — неизвестно, и сравнивать было бы нечего."""
    for key, options in VARIANTS.items():
        marks = {stamp(seed, key) for seed in range(len(options))}
        assert len(marks) == len(options), key
        assert all(mark.startswith(f"{key}#") for mark in marks)


def test_the_wording_reaches_the_history():
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, variant="water_almost#2")
            rows = await notifications.stats(session, by="variant", now_utc=NOW)
            assert [row.name for row in rows] == ["water_almost#2"]
    run(scenario)


def test_the_advice_carries_its_wording_all_the_way():
    """От правила до сообщения: подпись не должна теряться по дороге."""
    from services.context import DayContext, next_action
    from services.notifications import Prefs, decide

    ctx = DayContext(hour=15, water_ml=0, water_target=2000, day_seed=7)
    action = next_action(ctx)
    # Какой именно повод победит, решает срез дня — здесь это неважно.
    # Важно, что подпись формулировки у него есть и она осмысленная.
    assert "#" in action.wording
    assert action.wording.split("#")[0] in VARIANTS

    push = decide(action, user_id=1, prefs=Prefs(), local_hour=15, today=[],
                  history=[], now=NOW, snoozed=set())
    assert push.variant == action.wording


# --- как считается успех --------------------------------------------------


def test_a_pressed_button_is_success_and_a_mere_glance_is_not():
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, RESULT_ACTED, ago=5)
            await sent(session, KIND_WATER, RESULT_OPENED, ago=4)
            await sent(session, KIND_WATER, "", ago=3)
            await sent(session, KIND_WATER, "", ago=2)

            row = (await notifications.stats(session, now_utc=NOW))[0]
            assert row.sent == 4 and row.acted == 1 and row.opened == 1
            assert row.action_rate == 0.25       # главная мера
            assert row.open_rate == 0.5          # заглянули чаще, чем сделали
            assert row.ignored == 2
    run(scenario)


def test_asking_to_be_quiet_is_counted_as_harm_not_as_an_answer():
    async def scenario():
        async with db() as session:
            await sent(session, KIND_MEAL, RESULT_SNOOZED, ago=5)
            await sent(session, KIND_MEAL, RESULT_MUTED, ago=4)
            row = (await notifications.stats(session, now_utc=NOW))[0]
            assert row.action_rate == 0.0
            assert row.harm_rate == 1.0
    run(scenario)


def test_the_worst_topic_comes_first():
    """Отчёт нужен не чтобы порадоваться, а чтобы понять, что чинить."""
    async def scenario():
        async with db() as session:
            for _ in range(4):
                await sent(session, KIND_WATER, RESULT_ACTED, ago=6)
            for _ in range(4):
                await sent(session, KIND_MEAL, "", ago=5)
            rows = await notifications.stats(session, now_utc=NOW)
            assert rows[0].name == KIND_MEAL
    run(scenario)


def test_old_messages_do_not_muddy_the_picture():
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, RESULT_ACTED, ago=24 * 60)
            assert await notifications.stats(session, days=30, now_utc=NOW) == []
    run(scenario)


# --- сигналы, которые раньше терялись -------------------------------------


def test_opening_the_app_answers_the_recent_message():
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, ago=1)
            await notifications.note_app_open(session, 1, now_utc=NOW)
            row = (await notifications.stats(session, now_utc=NOW))[0]
            assert row.opened == 1
    run(scenario)


def test_opening_the_app_much_later_answers_nothing():
    """Через сутки это уже просто заход, а не ответ на сообщение."""
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, ago=30)
            await notifications.note_app_open(session, 1, now_utc=NOW)
            row = (await notifications.stats(session, now_utc=NOW))[0]
            assert row.opened == 0 and row.ignored == 1
    run(scenario)


def test_an_already_answered_message_is_not_overwritten():
    """Нажатая кнопка сильнее, чем «зашла потом». Не затираем сильное слабым."""
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, RESULT_ACTED, ago=1)
            await notifications.note_app_open(session, 1, now_utc=NOW)
            row = (await notifications.stats(session, now_utc=NOW))[0]
            assert row.acted == 1 and row.opened == 0
    run(scenario)


def test_switching_a_category_off_is_recorded_against_its_last_message():
    """Самый сильный отрицательный ответ: после этого текста человек пошёл
    в настройки и выключил тему совсем. Это и надо знать про текст."""
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, ago=2)
            await notifications.save_prefs(session, 1, water=False)
            row = (await notifications.stats(session, now_utc=NOW))[0]
            assert row.disabled == 1
            assert row.harm_rate == 1.0
    run(scenario)


def test_switching_a_category_back_on_marks_nothing():
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, ago=2)
            await notifications.save_prefs(session, 1, water=True)
            row = (await notifications.stats(session, now_utc=NOW))[0]
            assert row.disabled == 0
    run(scenario)


# --- как это выглядит у владельца -----------------------------------------


def test_the_owner_sees_plain_words_not_codes():
    async def scenario():
        async with db() as session:
            await sent(session, KIND_WATER, RESULT_ACTED, ago=3)
            rows = await notifications.stats(session, now_utc=NOW)
            text = "\n".join(_notification_lines(rows))
            assert KIND_RU[KIND_WATER] in text
            assert KIND_WATER not in text.replace(KIND_RU[KIND_WATER], "")
    run(scenario)


def test_the_owner_is_told_outright_when_something_does_not_work():
    async def scenario():
        async with db() as session:
            for _ in range(12):
                await sent(session, KIND_MEAL, "", ago=6)
            text = "\n".join(_notification_lines(
                await notifications.stats(session, now_utc=NOW)))
            assert "не работает совсем" in text
    run(scenario)


def test_a_message_people_open_is_not_called_dead():
    """У вечернего «на сегодня достаточно» кнопки действия нет вовсе.

    Назвать его неработающим было бы неправдой и плохим советом: там
    нечего нажимать и не должно быть.
    """
    async def scenario():
        async with db() as session:
            for _ in range(7):
                await sent(session, KIND_MEAL, RESULT_OPENED, ago=6)
            for _ in range(5):
                await sent(session, KIND_MEAL, "", ago=5)
            text = "\n".join(_notification_lines(
                await notifications.stats(session, now_utc=NOW)))
            assert "не работает совсем" not in text
            assert "нечего нажимать" in text
    run(scenario)


def test_a_working_topic_gets_no_warning():
    async def scenario():
        async with db() as session:
            for _ in range(12):
                await sent(session, KIND_MEAL, RESULT_ACTED, ago=6)
            text = "\n".join(_notification_lines(
                await notifications.stats(session, now_utc=NOW)))
            assert "переписать" not in text
    run(scenario)


def test_an_empty_month_says_so_instead_of_showing_nothing():
    async def scenario():
        async with db() as session:
            text = "\n".join(_notification_lines(
                await notifications.stats(session, now_utc=NOW)))
            assert "ничего не отправлялось" in text
    run(scenario)


def test_every_category_has_a_russian_name():
    from models.notification import KINDS

    assert set(KIND_RU) == set(KINDS)
