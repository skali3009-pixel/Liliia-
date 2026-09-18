"""Мир, награды и то, как бот учится на реакциях.

Три вещи, которые легче всего испортить в обратную сторону.

Событие мира должно ощущаться редким — иначе оно перестаёт быть событием.
Поздравление должно приходить один раз — повторённое, оно превращается в
насмешку. А обучение на реакциях не должно уметь выключить категорию
насовсем: два неотвеченных сообщения — не просьба замолчать навсегда.
"""

import asyncio
import contextlib
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Achievement, Base, GenderEnum, GoalEnum, Meal, User, WaterLog
from models.notification import (KIND_ACHIEVEMENT, KIND_MEAL, KIND_WATER,
                                 KIND_WORLD, RESULT_ACTED, RESULT_MUTED,
                                 RESULT_SNOOZED)
from services import notifications
from services.context import Action
from services.notifications import (ADAPT_FLOOR, ADAPT_MIN_SAMPLE, FATIGUE_WINDOW,
                                    MIN_SCORE, Prefs, Sent, TIRED_AT, WORLD_HOUR,
                                    appetite, decide, fatigue, kind_of)
from utils.game import ACHIEVEMENT_BY_CODE
from utils.timeframe import today_in

# От настоящей сегодняшней даты: «сегодня» в запросах к базе берётся по
# часам машины, и тест с датой из прошлого смотрел бы в пустой день.
NOW = datetime.combine(today_in("Europe/Moscow"), time(12, 0),
                       tzinfo=timezone.utc)



# --- усталость ------------------------------------------------------------


def ignored(count, *, first_hours_ago=2):
    return [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=first_hours_ago + i * 3))
            for i in range(count)]


def test_fatigue_grows_with_every_unanswered_message():
    steps = [fatigue(ignored(n)) for n in range(0, FATIGUE_WINDOW + 1)]
    assert steps == sorted(steps)
    assert steps[0] == 0.0
    assert steps[-1] > steps[1]


def test_an_answer_pushes_fatigue_back_down():
    silent = ignored(3)
    answered = [Sent(KIND_MEAL, "meal", NOW - timedelta(hours=2), result=RESULT_ACTED)]
    assert fatigue(answered + silent[1:]) < fatigue(silent)


def test_asking_to_wait_counts_less_than_saying_nothing():
    """«Позже» — это ответ. Молчание хуже."""
    silence = [Sent(KIND_WATER, "water", NOW - timedelta(hours=2))]
    asked = [Sent(KIND_WATER, "water", NOW - timedelta(hours=2), result=RESULT_SNOOZED)]
    assert fatigue(asked) < fatigue(silence)
    assert fatigue(asked) > 0        # но и не ноль: просили же помолчать


def test_silence_heals():
    """Плохая неделя не должна выключать бота навсегда."""
    stale = ignored(4, first_hours_ago=200)
    assert fatigue(stale, now=NOW) < fatigue(stale)
    assert fatigue(stale, now=NOW) == 0.0


def test_being_tired_raises_the_bar_gradually_not_in_one_step():
    """Планка поднимается плавно: чем меньше отвечают, тем весомее повод.

    Тема предложения нарочно другая, чем в истории: иначе сработало бы
    остывание — «эту тему уже поднимали», — и проверялось бы не то.
    """
    def passes(score, history):
        action = Action("water", "Вода", "…", "+250 мл", "water", score=score)
        return decide(action, user_id=1, prefs=Prefs(), local_hour=15, today=[],
                      history=history, now=NOW, snoozed=set()) is not None

    assert passes(0.7, [])                    # обычно проходит
    assert not passes(0.7, ignored(2))        # при лёгкой усталости — уже нет
    assert passes(1.4, ignored(2))            # но весомое проходит и тогда


def test_a_tired_person_still_hears_one_thing_a_day():
    assert fatigue(ignored(4)) >= TIRED_AT


# --- обучение на реакциях -------------------------------------------------


def test_too_little_evidence_changes_nothing():
    assert appetite({KIND_WATER: (ADAPT_MIN_SAMPLE - 1, 0)}, KIND_WATER) == 1.0
    assert appetite({}, KIND_WATER) == 1.0


def test_a_topic_nobody_answers_becomes_quieter():
    assert appetite({KIND_WATER: (8, 0)}, KIND_WATER) < 1.0


def test_a_topic_that_works_is_left_alone():
    assert appetite({KIND_WATER: (8, 6)}, KIND_WATER) == 1.0


def test_learning_can_turn_a_topic_down_but_never_off():
    """Два неотвеченных сообщения — не просьба замолчать навсегда.

    Выключить категорию человек может сам и явно, галочкой в настройках.
    Догадка бота такого права не даёт: иначе он тихо перестал бы писать о
    том, что человеку нужно, и никто бы не понял почему.
    """
    quietest = appetite({KIND_WATER: (50, 0)}, KIND_WATER)
    assert quietest >= ADAPT_FLOOR
    # Сильный повод — «остался один стакан» — проходит и на самой низкой
    # громкости.
    assert 1.35 * quietest > MIN_SCORE["balanced"]


def test_the_quieter_topic_really_is_quieter_in_the_decision():
    action = Action("water", "Вода", "…", "+250 мл", "water", score=0.8, amount=250)
    args = dict(user_id=1, prefs=Prefs(), local_hour=15, today=[], history=[],
                now=NOW, snoozed=set())
    assert decide(action, **args) is not None
    assert decide(action, appetite_for=ADAPT_FLOOR, **args) is None


# --- база: события, награды, статистика -----------------------------------


@contextlib.asynccontextmanager
async def db(**overrides):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        fields = dict(id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165,
                      current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                      onboarding_completed=True, timezone="Europe/Moscow",
                      daily_water_ml=2000, daily_calories=1800,
                      reminders_enabled=True, created_at=NOW - timedelta(days=30))
        fields.update(overrides)
        session.add(User(**fields))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def test_a_new_award_is_congratulated_once():
    async def scenario():
        async with db() as session:
            session.add(Achievement(user_id=1, code="streak_7",
                                    title="Неделя подряд", earned_at=NOW))
            await session.commit()

            award = await notifications.fresh_award(session, 1, now_utc=NOW)
            assert award["code"] == "streak_7"

            # Сказали — и больше не повторяем.
            push = notifications.Push(user_id=1, kind=KIND_ACHIEVEMENT,
                                      code="streak_7", text="…", cta="Посмотреть",
                                      target="world")
            await notifications.remember(session, push, day=NOW.date(), now_utc=NOW)
            assert await notifications.fresh_award(session, 1, now_utc=NOW) is None
    run(scenario)


def test_an_old_award_is_not_dug_up():
    async def scenario():
        async with db() as session:
            session.add(Achievement(user_id=1, code="streak_7", title="Неделя подряд",
                                    earned_at=NOW - timedelta(days=9)))
            await session.commit()
            assert await notifications.fresh_award(session, 1, now_utc=NOW) is None
    run(scenario)


def test_awards_belong_to_the_category_a_person_can_switch_off():
    for code in ACHIEVEMENT_BY_CODE:
        assert kind_of(code) == KIND_ACHIEVEMENT


def test_reaction_counts_are_gathered_per_topic():
    async def scenario():
        async with db() as session:
            for kind, result in ((KIND_WATER, RESULT_ACTED),
                                 (KIND_WATER, ""),
                                 (KIND_MEAL, RESULT_MUTED)):
                push = notifications.Push(user_id=1, kind=kind, code="x", text="…",
                                          cta="…", target="water")
                log_id = await notifications.remember(session, push, day=NOW.date(),
                                                      now_utc=NOW)
                if result:
                    await notifications.mark(session, 1, kind, result, now_utc=NOW)

            stats = await notifications.reactions(session, 1, now_utc=NOW)
            assert stats[KIND_WATER] == (2, 1)
            # «Сегодня не надо» — это ответ, но не тот, ради которого писали.
            assert stats[KIND_MEAL] == (1, 0)
    run(scenario)


# --- событие мира ---------------------------------------------------------


def test_the_world_event_has_its_own_hour_and_no_other():
    """Соревноваться весом с «в дневнике пусто» событие не может.

    Оно просит того же — закрыть пару заданий, — но не полезнее, а
    приятнее, и проиграло бы каждый раз. Поэтому у него свой момент: одно
    утро, и в остальные часы его нет вовсе.
    """
    from services.notifications import _world_action

    for hour in range(24):
        if hour != WORLD_HOUR:
            assert _world_action(1, NOW.date(), {"quests_done": 0}, hour) is None
    from services.notifications import _world_action

    action = _world_action(1, NOW.date(), {"quests_done": 0}, WORLD_HOUR)
    if action is None:
        pytest.skip("у этого человека в этот день события нет — так и задумано")
    assert action.target == "world"


def test_an_event_that_already_happened_is_not_announced():
    from services.notifications import _world_action
    from utils.events import EVENT_TARGET

    assert _world_action(1, NOW.date(), {"quests_done": EVENT_TARGET}, WORLD_HOUR) is None


def test_events_do_not_happen_every_day():
    """Событие каждый день перестаёт быть событием."""
    from services.notifications import _world_action

    days = [NOW.date() + timedelta(days=n) for n in range(30)]
    happened = sum(1 for day in days
                   if _world_action(1, day, {"quests_done": 0}, WORLD_HOUR) is not None)
    assert 0 < happened < len(days)


def test_the_event_message_says_what_is_left_to_do():
    from services.notifications import _world_action

    for day in (NOW.date() + timedelta(days=n) for n in range(30)):
        action = _world_action(1, day, {"quests_done": 1}, WORLD_HOUR)
        if action is not None:
            assert "Осталось закрыть 1" in action.text
            return
    pytest.fail("за месяц не нашлось ни одного события — проверять нечего")


def test_a_world_event_reaches_someone_in_its_own_hour():
    """Событие приходит утром того дня, когда оно есть.

    Ищем такой день перебором: события выпадают не каждый день, и это
    задумано — событие каждый день перестаёт быть событием.
    """
    from utils.events import event_for

    async def scenario():
        # 10:00 в Москве — тот самый час, когда мир показывает событие.
        morning = NOW - timedelta(hours=5)
        async with db(created_at=morning - timedelta(days=30)) as session:
            for offset in range(30):
                moment = morning + timedelta(days=offset)
                if event_for(1, moment.date().isoformat()) is None:
                    continue

                # Человек уже здесь — отметил воду, — но день ещё не закрыт,
                # и событию есть о чём попросить.
                session.add(WaterLog(user_id=1, amount_ml=300, logged_at=moment))
                await session.commit()

                planned = await notifications.due(session, now_utc=moment)
                if any(push.kind == KIND_WORLD for _, push, _ in planned):
                    return
            pytest.fail("за месяц ни одно событие не дошло до человека")
    run(scenario)
