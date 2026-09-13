"""Чем в чате пользуются, а чем нет.

Счёт заведён на время испытаний: «этой кнопкой не пользуются» — догадка
одного человека, а не факт, а убрав нужную кнопку, узнаёшь об этом от
рассерженного пользователя.

Считаем не только нажатия, но и людей: кнопка, которую один жмёт двадцать
раз в день, а остальные не трогают, — это не то же самое, что кнопка,
нужная всем по разу.
"""

import asyncio
import contextlib
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from keyboards.main_menu import MENU_ADD_MEAL, MENU_TEXTS, MENU_WATER
from models import Base, GenderEnum, GoalEnum, User
from services import buttons
from services.owner_reports import _button_lines
from utils.timeframe import today_in

NOW = datetime.combine(today_in("Europe/Moscow"), time(12, 0), tzinfo=timezone.utc)


@contextlib.asynccontextmanager
async def db(people: int = 3):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for uid in range(1, people + 1):
            session.add(User(id=uid, gender=GenderEnum.FEMALE, age=30, height_cm=165,
                             current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                             onboarding_completed=True, timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def test_the_label_loses_the_emoji():
    """В отчёте нужна подпись, а не картинка."""
    assert buttons.label(MENU_ADD_MEAL) == "Добавить еду"
    assert buttons.label(MENU_WATER) == "Вода"


def test_every_menu_button_has_a_readable_label():
    for text in MENU_TEXTS:
        name = buttons.label(text)
        assert name and not name.startswith(" ")
        assert len(name) <= 40, name        # влезает в колонку таблицы


def test_presses_and_people_are_counted_separately():
    """Одна кнопка, двадцать нажатий, один человек — это не популярность."""
    async def scenario():
        async with db() as session:
            for _ in range(20):
                await buttons.note(session, 1, MENU_WATER, now_utc=NOW)
            for uid in (1, 2, 3):
                await buttons.note(session, uid, MENU_ADD_MEAL, now_utc=NOW)

            rows = {row.button: row for row in await buttons.usage(session, now_utc=NOW)}
            assert rows["Вода"].presses == 20 and rows["Вода"].people == 1
            assert rows["Добавить еду"].presses == 3
            assert rows["Добавить еду"].people == 3
    run(scenario)


def test_the_report_ranks_by_people_not_by_presses():
    async def scenario():
        async with db() as session:
            for _ in range(20):
                await buttons.note(session, 1, MENU_WATER, now_utc=NOW)
            for uid in (1, 2, 3):
                await buttons.note(session, uid, MENU_ADD_MEAL, now_utc=NOW)

            order = [row.button for row in await buttons.usage(session, now_utc=NOW)]
            assert order[0] == "Добавить еду"
    run(scenario)


def test_one_person_a_day_makes_one_row():
    """Иначе таблица растёт по строке на каждое нажатие."""
    async def scenario():
        async with db() as session:
            from sqlalchemy import func, select

            from models import ButtonPress

            for _ in range(5):
                await buttons.note(session, 1, MENU_WATER, now_utc=NOW)
            rows = (await session.execute(
                select(func.count()).select_from(ButtonPress))).scalar_one()
            assert rows == 1
    run(scenario)


def test_old_presses_fall_out_of_the_window():
    async def scenario():
        async with db() as session:
            long_ago = NOW - timedelta(days=90)
            await buttons.note(session, 1, MENU_WATER, now_utc=long_ago)
            assert await buttons.usage(session, now_utc=NOW) == []
    run(scenario)


def test_the_report_says_who_is_almost_unused():
    async def scenario():
        async with db() as session:
            for uid in (1, 2, 3):
                await buttons.note(session, uid, MENU_ADD_MEAL, now_utc=NOW)
            await buttons.note(session, 1, MENU_WATER, now_utc=NOW)

            text = "\n".join(_button_lines(
                await buttons.usage(session, now_utc=NOW),
                await buttons.counting_since(session)))
            assert "Почти никому не нужны: Вода" in text
            assert "Добавить еду" in text
    run(scenario)


def test_the_report_reminds_that_counting_is_temporary():
    """Забытый счётчик тихо растит таблицу и остаётся в коде навсегда."""
    async def scenario():
        async with db() as session:
            await buttons.note(session, 1, MENU_WATER, now_utc=NOW)
            text = "\n".join(_button_lines(
                await buttons.usage(session, now_utc=NOW),
                await buttons.counting_since(session)))
            assert "временный" in text
            assert "set-buttons.sh off" in text
    run(scenario)


def test_switching_the_counter_off_hides_the_section(monkeypatch):
    monkeypatch.setattr(config, "BUTTON_STATS", False)
    assert _button_lines([buttons.Use("Вода", 5, 5)], date.today()) == []


def test_nothing_pressed_yet_says_so():
    assert "Пока ни одного" in "\n".join(_button_lines([], None))


def test_the_counter_can_be_switched_off_from_the_console():
    """Выключатель должен существовать, иначе «временный» — это навсегда."""
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "set-buttons.sh"
    assert script.exists()
    body = script.read_text(encoding="utf-8")
    assert "BUTTON_STATS" in body and "off" in body
