"""Чтобы шаги приходили с телефона сами.

Ограничение, вокруг которого всё построено: мини-приложение внутри Telegram
не может читать «Здоровье» — ни на айфоне, ни на Android. Это не вопрос
согласия человека, такого канала не существует у веб-страницы вовсе.

Обход: телефон присылает шаги сам, по личной ссылке. Ключ в ней — не пароль:
по нему можно только записать себе шаги за день и нельзя прочитать ничего.
Проверяется в основном это.
"""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from models import ActivityLevelEnum, Base, GenderEnum, GoalEnum, StepLog, User
from services import step_sync
from services import steps as step_service

USER = 1
OTHER = 2


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for user_id in (USER, OTHER):
            session.add(User(
                id=user_id, full_name="Лилия", gender=GenderEnum.FEMALE, age=30,
                height_cm=165, current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                activity_level=ActivityLevelEnum.MODERATE, daily_steps=8000,
                onboarding_completed=True, timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


@pytest.fixture(autouse=True)
def clean():
    step_service.forget_pushes()
    yield
    step_service.forget_pushes()


# --- Ключ ------------------------------------------------------------------

def test_the_key_is_personal_and_stable():
    async def scenario():
        async with db() as session:
            user = await session.get(User, USER)
            first = await step_service.sync_token(session, user)
            assert len(first) == step_service.TOKEN_LENGTH
            # Повторный вызов не выдаёт новый: ссылка уже отдана телефону.
            assert await step_service.sync_token(session, user) == first

            other = await session.get(User, OTHER)
            assert await step_service.sync_token(session, other) != first
    run(scenario)


def test_changing_the_key_kills_the_old_link():
    """Так отзывают ссылку, которая куда-то утекла."""
    async def scenario():
        async with db() as session:
            user = await session.get(User, USER)
            old = await step_service.sync_token(session, user)
            new = await step_service.sync_token(session, user, renew=True)

            assert new != old
            assert await step_service.by_token(session, old) is None
            assert (await step_service.by_token(session, new)).id == USER
    run(scenario)


def test_an_unknown_key_belongs_to_nobody():
    async def scenario():
        async with db() as session:
            assert await step_service.by_token(session, "выдуманный") is None
            assert await step_service.by_token(session, "") is None
    run(scenario)


# --- Ограничитель ----------------------------------------------------------

def test_a_looping_automation_is_stopped():
    """Расписание шлёт раз в несколько часов; зациклившееся — тысячи раз."""
    allowed = sum(step_service.push_allowed("ключ")
                  for _ in range(step_service.SYNC_PER_HOUR + 20))
    assert allowed == step_service.SYNC_PER_HOUR


def test_the_limit_lets_go_after_an_hour():
    now = datetime.now(timezone.utc)
    for _ in range(step_service.SYNC_PER_HOUR):
        step_service.push_allowed("ключ", now=now)

    assert step_service.push_allowed("ключ", now=now) is False
    assert step_service.push_allowed("ключ", now=now + timedelta(hours=1, minutes=1))


def test_the_limit_is_personal():
    for _ in range(step_service.SYNC_PER_HOUR):
        step_service.push_allowed("первый")
    assert step_service.push_allowed("второй") is True


# --- Ссылка и инструкция ---------------------------------------------------

def test_the_link_ends_where_the_number_goes(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "https://aura.example/")
    link = step_sync.link_for("КЛЮЧ")
    assert link == "https://aura.example/hook/steps/КЛЮЧ?steps="
    assert link.endswith("=") , "число подставляется в конец — так проще в «Командах»"


def test_without_a_site_there_is_no_link_and_it_is_explained(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "")
    assert step_sync.link_for("КЛЮЧ") == ""
    assert "кнопкой" in step_sync.instructions("")


def test_the_instruction_says_why_and_how_and_about_safety(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "https://aura.example")
    text = step_sync.instructions(step_sync.link_for("КЛЮЧ"))

    assert "«Команды»" in text and "Здоровь" in text
    assert "22:00" in text, "без расписания присылка не автоматическая"
    assert "Android" in text
    assert "поменяй" in text, "человек должен знать, что ссылку можно отозвать"
    assert "КЛЮЧ" in text


def test_the_instruction_does_not_promise_a_direct_connection(monkeypatch):
    """Обещать «подключимся к Здоровью» нельзя: это неправда."""
    monkeypatch.setattr(config, "WEBAPP_URL", "https://aura.example")
    text = step_sync.instructions(step_sync.link_for("КЛЮЧ")).lower()
    for lie in ("подключим", "подключится к здоровью", "синхронизируется автоматически с"):
        assert lie not in text, lie


# --- Записи с телефона -----------------------------------------------------

def test_a_pushed_number_is_marked_as_coming_from_the_phone():
    async def scenario():
        async with db() as session:
            await step_service.record(session, USER, 9200,
                                      source=step_service.SOURCE_PHONE)
            row = (await session.execute(
                __import__("sqlalchemy").select(StepLog))).scalars().one()
            assert row.source == step_service.SOURCE_PHONE
            assert await step_service.last_sync(session, USER) is not None
    run(scenario)


def test_a_hand_typed_number_is_not_counted_as_a_sync():
    async def scenario():
        async with db() as session:
            await step_service.record(session, USER, 5000)
            assert await step_service.last_sync(session, USER) is None
    run(scenario)
