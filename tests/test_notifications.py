"""Тесты движка уведомлений: когда бот пишет первым, а когда молчит.

Молчание здесь — основное поведение, поэтому и проверок на молчание больше.
Каждая из них про отдельную причину: человек спит, выключил категорию,
просил помолчать, сам только что зашёл, уже получил сегодня своё, недавно
слышал ту же тему, перестал отвечать, повод слишком мелкий.
"""

import asyncio
import contextlib
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, GenderEnum, GoalEnum, User
from models.notification import (KIND_MEAL, KIND_MOVEMENT, KIND_TURN,
                                 KIND_WATER, PACE_ACTIVE, PACE_MINIMAL)
from services.context import Action
from services.notifications import (BUDGET, RECENT_OPEN_MINUTES, Prefs, Sent,
                                    decide, history_for, kind_of, mark,
                                    prefs_for, remember, save_prefs, snooze,
                                    snoozed_kinds, sent_today, tired)

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)
DAY = date(2026, 9, 8)

WATER = Action("water", "Вода", "Стакан?", "+250 мл", "water", score=1.1, amount=250)
MEAL = Action("meal", "Еда", "Запишем?", "Записать еду", "meal", score=1.2)
SMALL = Action("checkin", "Состояние", "Как ты?", "Отметить", "checkin", score=0.5)


def ask(action=WATER, **over):
    """Одно решение со здоровым окружением: всё разрешено, ничего не было."""
    args = dict(user_id=1, prefs=Prefs(), local_hour=15, today=[], history=[],
                now=NOW, snoozed=set())
    args.update(over)
    return decide(action, **args)


# --- когда пишем ----------------------------------------------------------


def test_a_worthwhile_nudge_goes_out():
    push = ask()
    assert push is not None
    assert push.kind == KIND_WATER
    assert push.amount == 250          # кнопка «+250 мл» работает из чата


def test_the_advice_keeps_its_own_words():
    """Движок ничего не переписывает: текст приходит из services/context.py."""
    push = ask()
    assert push.text == WATER.text and push.cta == WATER.cta


# --- когда молчим ---------------------------------------------------------


def test_nothing_to_say_means_nothing_is_sent():
    assert ask(None) is None


def test_night_is_left_alone():
    assert ask(local_hour=3) is None
    assert ask(local_hour=23) is None
    # А в свой час — пишем: тишина ночью, а не вообще.
    assert ask(local_hour=9) is not None


def test_quiet_hours_can_be_moved_and_still_wrap_midnight():
    owl = Prefs(quiet_from=1, quiet_to=10)
    assert ask(prefs=owl, local_hour=23) is not None
    assert ask(prefs=owl, local_hour=9) is None


def test_a_switched_off_category_is_silent():
    assert ask(prefs=Prefs(water=False)) is None
    # Другая категория при этом продолжает работать.
    assert ask(MEAL, prefs=Prefs(water=False)) is not None


def test_later_means_later():
    assert ask(snoozed={KIND_WATER}) is None


def test_someone_who_is_here_right_now_is_not_chased():
    """Она всё это только что видела своими глазами — в приложении или в чате."""
    just_now = NOW - timedelta(minutes=RECENT_OPEN_MINUTES - 5)
    assert ask(last_seen=just_now) is None
    long_ago = NOW - timedelta(hours=5)
    assert ask(last_seen=long_ago) is not None


def test_the_daily_budget_is_a_ceiling():
    three = [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=h)) for h in (9, 7, 5)]
    assert len(three) == BUDGET["balanced"]
    assert ask(today=three) is None


def test_messages_do_not_come_back_to_back():
    recent = [Sent(KIND_MEAL, "meal", NOW - timedelta(minutes=30))]
    assert ask(today=recent) is None
    older = [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=4))]
    assert ask(today=older) is not None


def test_the_same_subject_does_not_repeat_within_hours():
    said = [Sent(KIND_WATER, "water", NOW - timedelta(hours=2))]
    assert ask(today=[], history=said) is None
    stale = [Sent(KIND_WATER, "water", NOW - timedelta(hours=9))]
    assert ask(today=[], history=stale) is not None


def test_a_small_reason_is_not_worth_a_notification():
    """На экране такой совет по-прежнему виден — он просто не звонит."""
    assert ask(SMALL) is None


MIDDLING = Action("meal", "Еда", "Запишем?", "Записать еду", "meal", score=0.7)


def test_someone_who_stopped_answering_hears_much_less():
    """Не тишина навсегда, а поднятая планка.

    Замолчать совсем было бы ошибкой: человек тогда никогда не получит
    возможности ответить, счёт молчания не обнулится, и бот выключит себя
    сам без её ведома. Поэтому одно по-настоящему весомое сообщение в день
    проходит, а всё среднее — нет.
    """
    ignored = [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=h)) for h in (30, 28, 26)]
    assert tired(ignored)

    # Обычно такой повод проходит.
    assert ask(MIDDLING, history=[], today=[]) is not None
    # На уставшем — уже нет.
    assert ask(MIDDLING, history=ignored, today=[]) is None
    # А весомый — всё ещё да.
    assert ask(WATER, history=ignored, today=[]) is not None


def test_a_tired_person_gets_one_message_a_day_at_most():
    ignored = [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=h)) for h in (30, 28, 26)]
    one_today = [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=6))]
    assert ask(WATER, history=ignored, today=one_today) is None


def test_one_answer_is_enough_to_start_talking_again():
    mixed = [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=30), result="acted"),
             Sent(KIND_MEAL, "meal", NOW - timedelta(hours=28)),
             Sent(KIND_MEAL, "meal", NOW - timedelta(hours=26))]
    assert not tired(mixed)


# --- частота --------------------------------------------------------------


def test_the_quietest_setting_really_is_quieter():
    minimal = Prefs(pace=PACE_MINIMAL)
    one = [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=9))]
    assert ask(prefs=minimal, today=one) is None
    # На «сбалансированно» то же самое сообщение проходит.
    assert ask(today=one) is not None


def test_the_liveliest_setting_lets_smaller_things_through():
    assert ask(SMALL, prefs=Prefs(pace=PACE_ACTIVE)) is not None


def test_every_advice_belongs_to_a_category_a_person_can_switch_off():
    for code in ("water", "meal", "protein", "fiber", "prep", "steps",
                 "movement", "rest", "checkin", "progress"):
        assert kind_of(code) in {KIND_WATER, KIND_MEAL, KIND_MOVEMENT, KIND_TURN}


# --- хранение -------------------------------------------------------------


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


def test_settings_default_to_everything_on_without_writing_a_row():
    async def scenario():
        async with db() as session:
            prefs = await prefs_for(session, 1)
            assert prefs == Prefs()
    run(scenario)


def test_settings_survive_and_ignore_nonsense():
    async def scenario():
        async with db() as session:
            saved = await save_prefs(session, 1, water=False, pace="загадочно",
                                     quiet_from=99, evening=False)
            assert saved.water is False and saved.evening is False
            assert saved.pace == Prefs().pace       # незнакомое не принимаем
            assert saved.quiet_from == 23           # час не бывает 99-м
            assert (await prefs_for(session, 1)).water is False
    run(scenario)


def test_history_remembers_what_was_sent_and_how_it_ended():
    async def scenario():
        async with db() as session:
            push = ask()
            await remember(session, push, day=DAY, now_utc=NOW)
            assert len(await sent_today(session, 1, DAY)) == 1

            await mark(session, 1, KIND_WATER, "acted", now_utc=NOW)
            rows = await history_for(session, 1, now_utc=NOW)
            assert [row.result for row in rows] == ["acted"]
    run(scenario)


def test_snooze_expires_by_itself():
    async def scenario():
        async with db() as session:
            await snooze(session, 1, KIND_WATER, until=NOW + timedelta(hours=3))
            assert await snoozed_kinds(session, 1, now_utc=NOW) == {KIND_WATER}
            later = NOW + timedelta(hours=4)
            assert await snoozed_kinds(session, 1, now_utc=later) == set()
    run(scenario)


def test_asking_twice_replaces_the_first_request():
    async def scenario():
        async with db() as session:
            await snooze(session, 1, KIND_WATER, until=NOW + timedelta(hours=1))
            await snooze(session, 1, KIND_WATER, until=NOW + timedelta(hours=8))
            later = NOW + timedelta(hours=4)
            assert await snoozed_kinds(session, 1, now_utc=later) == {KIND_WATER}
    run(scenario)
