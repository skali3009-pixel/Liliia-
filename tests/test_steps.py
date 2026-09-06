"""Шагомер: цель, кольцо, серия и рейтинг.

Одно ограничение стоит помнить, читая эти тесты. Мини-приложение внутри
Telegram не умеет читать шаги само — ни «Здоровье» на айфоне, ни датчик ему
не доступны. Число вносит человек. Значит, рейтинг строится на том, что люди
вписывают сами, и защищать его запретами бессмысленно: здесь потолок, выше
которого приписка просто не считается.
"""

import asyncio
import contextlib
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (ActivityLevelEnum, Base, GenderEnum, GoalEnum, User)
from services import steps as step_service
from services import teams
from utils.timeframe import today_in

TODAY = date(2026, 9, 6)


@contextlib.asynccontextmanager
async def db(people=(1,)):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for index, user_id in enumerate(people):
            session.add(User(
                id=user_id, full_name=f"Человек{index} Фамилия",
                gender=GenderEnum.FEMALE, age=30, height_cm=165,
                current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                activity_level=ActivityLevelEnum.MODERATE,
                onboarding_completed=True, timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


async def walk(session, user_id, day, steps):
    await step_service.record(session, user_id, steps, day=day)


# --- Цель ------------------------------------------------------------------

def test_the_goal_is_the_persons_own_choice():
    async def scenario():
        async with db() as session:
            user = await session.get(User, 1)
            assert step_service.goal_for(user) == 10000  # по активности

            user.daily_steps = 6000
            assert step_service.goal_for(user) == 6000
    run(scenario)


def test_an_absurd_goal_is_brought_back_into_range():
    assert step_service.clean_goal(1_000_000) == step_service.MAX_GOAL
    assert step_service.clean_goal(10) == step_service.MIN_GOAL
    assert step_service.clean_goal("8 000") == 8000
    assert step_service.clean_goal("восемь тысяч") is None
    assert step_service.clean_goal(0) is None


def test_a_typo_in_the_step_count_is_capped_not_stored():
    """Полсотни километров пешком — суточный переход, а не день с телефоном."""
    assert step_service.clean_steps(999_999) == step_service.MAX_DAILY
    assert step_service.clean_steps(-5) == 0
    assert step_service.clean_steps("12 345") == 12345
    assert step_service.clean_steps("много") is None


# --- Запись ----------------------------------------------------------------

def test_entering_steps_twice_corrects_the_day_instead_of_doubling_it():
    """Телефон показывает итог с начала суток — складывать записи нельзя."""
    async def scenario():
        async with db() as session:
            await walk(session, 1, TODAY, 3000)
            await walk(session, 1, TODAY, 7500)
            assert await step_service.on_day(session, 1, TODAY) == 7500
    run(scenario)


def test_the_state_gathers_the_day_the_week_and_the_best():
    async def scenario():
        async with db() as session:
            for shift, steps in ((0, 9000), (1, 12000), (2, 4000), (9, 30000)):
                await walk(session, 1, TODAY - timedelta(days=shift), steps)

            user = await session.get(User, 1)
            user.daily_steps = 8000
            state = await step_service.state(session, user)
            # Неделя — последние семь дней, старое в неё не попадает.
            assert state.week == 9000 + 12000 + 4000
            assert state.best == 30000
            assert state.total == 55000
    run(scenario)


# --- Серия -----------------------------------------------------------------

def test_the_streak_counts_days_with_the_goal_reached():
    async def scenario():
        async with db() as session:
            for shift in range(5):
                await walk(session, 1, TODAY - timedelta(days=shift), 9000)
            assert await step_service.streak(session, 1, 8000, today=TODAY) == 5
    run(scenario)


def test_an_unfinished_today_does_not_break_the_streak():
    """Обнулять серию в полдень — наказание за то, что человек зашёл."""
    async def scenario():
        async with db() as session:
            for shift in range(1, 5):
                await walk(session, 1, TODAY - timedelta(days=shift), 9000)
            await walk(session, 1, TODAY, 200)

            assert await step_service.streak(session, 1, 8000, today=TODAY) == 4
    run(scenario)


def test_a_missed_day_ends_the_streak():
    async def scenario():
        async with db() as session:
            await walk(session, 1, TODAY, 9000)
            await walk(session, 1, TODAY - timedelta(days=1), 1000)
            await walk(session, 1, TODAY - timedelta(days=2), 9000)

            assert await step_service.streak(session, 1, 8000, today=TODAY) == 1
    run(scenario)


# --- Рейтинг ---------------------------------------------------------------

def test_the_week_table_is_sorted_and_marks_me():
    async def scenario():
        async with db(people=(1, 2, 3)) as session:
            await walk(session, 1, TODAY, 5000)
            await walk(session, 2, TODAY, 12000)
            await walk(session, 3, TODAY, 9000)

            rows = await step_service.week_rows(session, [1, 2, 3], me=1, today=TODAY)
            assert [row.user_id for row in rows] == [2, 3, 1]
            assert [row.is_me for row in rows] == [False, False, True]
            assert step_service.place_of(rows, 1) == 3
    run(scenario)


def test_padding_the_number_stops_paying_off_at_the_cap():
    """Соревнование на своих же числах защищают не запретом, а потолком."""
    async def scenario():
        async with db(people=(1, 2)) as session:
            await walk(session, 1, TODAY, step_service.MAX_DAILY)
            await walk(session, 2, TODAY, step_service.RANKED_CAP)

            rows = await step_service.week_rows(session, [1, 2], today=TODAY)
            assert rows[0].steps == rows[1].steps == step_service.RANKED_CAP
    run(scenario)


def test_the_table_shows_a_first_name_not_a_full_one():
    async def scenario():
        async with db() as session:
            rows = await step_service.week_rows(session, [1], today=TODAY)
            assert rows[0].name == "Человек0"
    run(scenario)


def test_the_table_counts_days_with_the_goal_reached():
    async def scenario():
        async with db() as session:
            user = await session.get(User, 1)
            user.daily_steps = 8000
            await session.commit()
            for shift, steps in ((0, 9000), (1, 3000), (2, 8000)):
                await walk(session, 1, TODAY - timedelta(days=shift), steps)

            rows = await step_service.week_rows(session, [1], today=TODAY)
            assert rows[0].days == 2
    run(scenario)


def test_the_global_table_skips_people_who_did_not_walk():
    """Список из сотни нулей никого не вдохновляет."""
    async def scenario():
        async with db(people=(1, 2, 3)) as session:
            await walk(session, 2, TODAY, 7000)

            rows = await step_service.global_top(session, today=TODAY)
            assert [row.user_id for row in rows] == [2]
    run(scenario)


def test_i_am_in_the_global_table_even_with_an_empty_week():
    """Иначе человек не понимает, откуда считается его место."""
    async def scenario():
        async with db(people=(1, 2)) as session:
            await walk(session, 2, TODAY, 7000)

            rows = await step_service.global_top(session, me=1, today=TODAY)
            assert {row.user_id for row in rows} == {1, 2}
            assert step_service.place_of(rows, 1) == 2
    run(scenario)


# --- Команда ---------------------------------------------------------------

def test_a_team_is_created_joined_and_ranked_inside():
    async def scenario():
        async with db(people=(1, 2, 3)) as session:
            status, team = await teams.create(session, 1, "  Лисы  ")
            assert status == "ok" and team.name == "Лисы"

            for user_id in (2, 3):
                assert (await teams.join(session, user_id, team.code))[0] == "ok"

            await walk(session, 1, TODAY, 4000)
            await walk(session, 2, TODAY, 11000)
            await walk(session, 3, TODAY, 8000)

            board = await teams.board(session, 1, today=TODAY)
            assert board.name == "Лисы"
            assert board.people == 3
            assert board.total == 23000
            assert [row.user_id for row in board.rows] == [2, 3, 1]
    run(scenario)


def test_a_person_belongs_to_one_team_only():
    """Иначе «внутри команды» означает у каждого своё."""
    async def scenario():
        async with db(people=(1, 2)) as session:
            _, first = await teams.create(session, 1, "Лисы")
            _, second = await teams.create(session, 2, "Волки")

            assert (await teams.join(session, 1, second.code))[0] == "already"
            assert (await teams.create(session, 1, "Ещё одна"))[0] == "already"
            assert (await teams.join(session, 1, first.code))[0] == "same"
    run(scenario)


def test_a_team_without_a_name_is_not_created():
    async def scenario():
        async with db() as session:
            assert (await teams.create(session, 1, "   "))[0] == "no_name"
    run(scenario)


def test_a_wrong_code_says_so_instead_of_creating_something():
    async def scenario():
        async with db() as session:
            status, team = await teams.join(session, 1, "какой-то")
            assert status == "no_team" and team is None
    run(scenario)


def test_a_full_team_does_not_take_more_people():
    async def scenario():
        people = tuple(range(1, teams.MAX_MEMBERS + 3))
        async with db(people=people) as session:
            _, team = await teams.create(session, 1, "Лисы")
            for user_id in people[1:teams.MAX_MEMBERS]:
                assert (await teams.join(session, user_id, team.code))[0] == "ok"

            assert (await teams.join(session, people[-1], team.code))[0] == "full"
    run(scenario)


def test_the_last_one_out_takes_the_team_with_them():
    """Пустая команда никому не нужна, а её код продолжал бы работать."""
    async def scenario():
        async with db(people=(1, 2)) as session:
            _, team = await teams.create(session, 1, "Лисы")
            await teams.join(session, 2, team.code)

            await teams.leave(session, 1)
            assert await teams.my_team(session, 2) is not None

            await teams.leave(session, 2)
            assert (await teams.join(session, 1, team.code))[0] == "no_team"
    run(scenario)


def test_only_the_owner_renames_the_team():
    async def scenario():
        async with db(people=(1, 2)) as session:
            _, team = await teams.create(session, 1, "Лисы")
            await teams.join(session, 2, team.code)

            assert await teams.rename(session, 2, "Волки") is False
            assert await teams.rename(session, 1, "Волки") is True
            assert (await teams.my_team(session, 2)).name == "Волки"
    run(scenario)


# --- Игровой слой ----------------------------------------------------------

def test_the_daily_quest_appears_and_closes():
    from utils.game import build_quests

    def quest(steps, goal):
        quests = build_quests(
            meals_count=0, calories=0, calories_norm=1600, water_ml=0,
            water_norm_ml=2000, fiber_g=0, fiber_norm_g=20, workouts_today=0,
            days_since_measure=1, steps=steps, steps_goal=goal)
        return next(q for q in quests if q.code == "steps")

    assert quest(3000, 8000).done is False
    assert quest(8000, 8000).done is True
    # Без цели задание не закрывается само собой.
    assert quest(0, 0).done is False


def test_walking_earns_its_own_awards():
    from utils.game import earned_codes

    base = dict(meals_total=0, streak=0, level=1, weight_lost_kg=0,
                waist_lost_cm=0, workouts_total=0)
    assert "steps_first" in earned_codes(**base, steps_total=100)
    assert "steps_week" in earned_codes(**base, steps_streak=7)
    assert "steps_100k" in earned_codes(**base, steps_total=100_000)
    assert "steps_marathon" in earned_codes(**base, steps_best=20_000)
    assert earned_codes(**base) == set()


# --- Ввод из чата ----------------------------------------------------------
# Тому, кто живёт в переписке и приложение не открывает, нужен путь в чате —
# иначе он выпадает из всей затеи с командой и рейтингом.

class FakeState:
    def __init__(self):
        self.state = None
        self.cleared = False

    async def set_state(self, value):
        self.state = value

    async def clear(self):
        self.state, self.cleared = None, True


class FakeMessage:
    def __init__(self, text="", user_id=1):
        self.text = text
        self.from_user = type("U", (), {"id": user_id})()
        self.said: list[str] = []

    async def answer(self, text, **kwargs):
        self.said.append(text)
        return self


@contextlib.asynccontextmanager
async def chat_db():
    """База, подменённая обработчику: он ходит в неё сам."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def get_session():
        async with maker() as session:
            yield session

    import db as db_module
    import handlers.steps as module

    original, original_db = module.get_session, db_module.get_session
    module.get_session = get_session
    db_module.get_session = get_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(
            id=1, full_name="Лилия", gender=GenderEnum.FEMALE, age=30,
            height_cm=165, current_weight_kg=60, goal=GoalEnum.LOSE_WEIGHT,
            activity_level=ActivityLevelEnum.MODERATE, onboarding_completed=True,
            daily_calories=1600, daily_protein_g=120, daily_fat_g=48,
            daily_carbs_g=160, daily_fiber_g=22, daily_water_ml=2100,
            daily_steps=8000, timezone="Europe/Moscow"))
        await session.commit()
    try:
        yield maker
    finally:
        module.get_session = original
        db_module.get_session = original_db
        await engine.dispose()


def test_a_number_sent_in_the_chat_is_written_down():
    async def scenario():
        from handlers.steps import take_number

        async with chat_db() as maker:
            message, state = FakeMessage("9200"), FakeState()
            await take_number(message, state)

            async with maker() as session:
                today = today_in("Europe/Moscow")
                assert await step_service.on_day(session, 1, today) == 9200

            assert "9200" in message.said[0]
            assert state.cleared
    run(scenario)


def test_the_chat_answer_shows_the_same_numbers_as_the_ring():
    async def scenario():
        from handlers.steps import take_number

        async with chat_db():
            message = FakeMessage("9200")
            await take_number(message, FakeState())
            text = message.said[0]
            assert "из 8000" in text and "Норма пройдена" in text
            assert "За неделю" in text
    run(scenario)


def test_falling_short_is_told_in_minutes_not_in_shame():
    async def scenario():
        from handlers.steps import take_number

        async with chat_db():
            message = FakeMessage("6000")
            await take_number(message, FakeState())
            assert "Осталось 2000" in message.said[0]
            assert "минут пешком" in message.said[0]
    run(scenario)


def test_a_wrong_answer_asks_again_instead_of_dropping_the_person():
    async def scenario():
        from handlers.steps import take_number

        async with chat_db():
            message, state = FakeMessage("много ходила"), FakeState()
            await take_number(message, state)

            assert "цифрой" in message.said[0]
            # Человек ошибся, а не передумал: состояние остаётся.
            assert state.cleared is False
    run(scenario)


def test_the_command_writes_the_number_right_away():
    async def scenario():
        from handlers.steps import steps_command

        async with chat_db():
            message, state = FakeMessage("/steps 7000"), FakeState()
            command = type("C", (), {"args": "7000"})()
            await steps_command(message, state, command)

            assert "7000" in message.said[0]
    run(scenario)


def test_the_command_without_a_number_asks_for_one():
    async def scenario():
        from handlers.steps import steps_command

        async with chat_db():
            message, state = FakeMessage("/steps"), FakeState()
            command = type("C", (), {"args": None})()
            await steps_command(message, state, command)

            assert "Сколько шагов" in message.said[0]
            assert state.state is not None
    run(scenario)


def test_the_button_says_what_is_already_written_down():
    """Новое число заменяет прежнее — человек должен это понимать заранее."""
    async def scenario():
        from handlers.steps import ask_steps, take_number

        async with chat_db():
            await take_number(FakeMessage("5000"), FakeState())

            message = FakeMessage()
            await ask_steps(message, FakeState())
            assert "5000" in message.said[0]
            assert "заменит" in message.said[0]
    run(scenario)


def test_a_menu_button_ends_the_waiting():
    async def scenario():
        from aiogram.dispatcher.event.bases import SkipHandler
        from handlers.steps import leave_waiting
        from keyboards.main_menu import MENU_WATER

        state = FakeState()
        with pytest.raises(SkipHandler):
            await leave_waiting(FakeMessage(MENU_WATER), state)
        assert state.cleared
    run(scenario)


def test_the_chat_button_is_in_the_menu_and_the_hint_names_it():
    from keyboards.main_menu import MENU_STEPS, main_menu_keyboard
    from services import turn as turn_service

    buttons = {b.text for row in main_menu_keyboard().keyboard for b in row}
    assert MENU_STEPS in buttons
    assert turn_service.CHAT_BUTTON["steps"] == MENU_STEPS


def test_the_streak_is_written_in_proper_russian():
    """«1 дней подряд» — мелочь, которую видно в каждом ответе бота."""
    from handlers.steps import render

    def line(days: int) -> str:
        walk = step_service.Steps(today=9000, goal=8000, week=9000,
                                  streak=days, total=9000, best=9000)
        return render(walk)

    assert "1 день подряд" in line(1)
    assert "2 дня подряд" in line(2)
    assert "5 дней подряд" in line(5)
    assert "21 день подряд" in line(21)
    # И два разных счётчика в одном сообщении не путаются между собой.
    assert "с нормой шагов" in line(3)
