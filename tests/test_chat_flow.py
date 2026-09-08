"""Чтобы записать еду, не надо ничего нажимать заранее.

Тестировщицы решили, что перед каждым фото нужно жать «Добавить еду». Они
не ошибались в наблюдении — только в объяснении. Фото обрабатывалось лишь
тогда, когда человек не был занят другим разговором: нажал «Шаги» и не
ввёл число, начал править рост, открыл «что-то не так» — и следующее фото
не разбирал никто. Ни ответа, ни ошибки. А «Добавить еду» сбрасывала
незаконченный сценарий, и фото наконец доходило.

Здесь проверяется, что этого больше не повторится: фото и голосовое
работают из любого разговора, а на непонятое бот отвечает словами.
"""

import asyncio
import contextlib
import json

import pytest
from aiogram.filters import StateFilter
from aiogram.fsm.storage.base import StorageKey
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import db as db_module
from models import Base, FsmState
from states.food import FoodStates
from states.onboarding import OnboardingStates


def run(scenario):
    asyncio.run(scenario())


# --- фото доходит из любого разговора --------------------------------------


def _handler_filters(func_name: str):
    """Фильтры, с которыми зарегистрирован обработчик."""
    import handlers.food as food

    for observer in food.router.observers.values():
        for handler in observer.handlers:
            if handler.callback.__name__ == func_name:
                return handler.filters
    raise AssertionError(f"обработчик {func_name} не зарегистрирован")


class FakeEvent:
    """Сообщение ровно с тем, что смотрят фильтры."""

    def __init__(self, *, photo=None, voice=None):
        self.photo = photo
        self.voice = voice
        self.text = None
        self.caption = None


async def _accepts(name, event, raw_state) -> bool:
    """Пропустят ли фильтры обработчика это событие в этом состоянии."""
    for item in _handler_filters(name):
        result = await item.call(event, raw_state=raw_state)
        if not result:
            return False
    return True


@pytest.mark.parametrize("name,event", [
    ("handle_food_photo", FakeEvent(photo=["file"])),
    ("handle_food_voice", FakeEvent(voice=object())),
])
def test_food_is_accepted_in_any_conversation_except_the_form(name, event):
    """Проверяем поведение фильтра, а не его устройство.

    Раньше здесь было «принимается только вне сценариев», и человек,
    застрявший в «Шагах» или в правке профиля, оставался без ответа.
    Единственное исключение — анкета: там фото не еда, а сбитые ответы.
    """
    async def scenario():
        assert await _accepts(name, event, None), "вне сценариев — обязано"
        assert await _accepts(name, event, "StepStates:waiting_number"), (
            "застряла в «Шагах» — фото снова некому разобрать"
        )
        assert await _accepts(name, event, "ProfileStates:height"), (
            "начала править профиль — фото снова некому разобрать"
        )
        assert await _accepts(name, event, FoodStates.confirming.state)
        assert not await _accepts(name, event, OnboardingStates.age.state), (
            "во время анкеты фото не должно сбивать ответы"
        )
    run(scenario)


def test_a_stuck_scenario_is_dropped_by_a_photo():
    """Фото отменяет чужой незаконченный разговор, а не спорит с ним."""
    import handlers.food as food
    import inspect

    body = inspect.getsource(food.handle_food_photo)
    assert "state.clear()" in body
    assert "FoodStates" in body      # свой же разговор не сбрасываем


# --- бот не молчит ---------------------------------------------------------


class FakeState:
    def __init__(self):
        self.cleared = False

    async def clear(self):
        self.cleared = True


class FakeMessage:
    def __init__(self):
        self.said: list[str] = []

    async def answer(self, text, **kwargs):
        self.said.append(text)


def test_something_unknown_gets_words_not_silence():
    async def scenario():
        from handlers.fallback import did_not_understand

        message, state = FakeMessage(), FakeState()
        await did_not_understand(message, state)
        said = " ".join(message.said)
        assert "фото" in said and "голосов" in said
        # И объясняем главное: заранее ничего нажимать не надо.
        assert "не надо" in said
        assert state.cleared, "застрявший сценарий должен отпускать"
    run(scenario)


def test_a_photo_sent_as_a_file_is_explained():
    """Айфон умеет отправить снимок документом. Раньше это было молчание."""
    async def scenario():
        from handlers.fallback import not_a_photo

        message, state = FakeMessage(), FakeState()
        await not_a_photo(message, state)
        said = " ".join(message.said)
        assert "файлом" in said
        assert "словами" in said        # всегда есть запасной путь
    run(scenario)


def test_the_fallback_is_the_very_last_router():
    """Иначе он перехватит то, что должны разобрать сценарии."""
    import bot

    names = [router.name for router in bot.dp.sub_routers]
    assert names[-1] == "fallback"


# --- разговор переживает перезапуск ----------------------------------------


@contextlib.asynccontextmanager
async def storage():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def get_session():
        async with maker() as session:
            yield session

    import services.fsm_storage as module

    original_module, original_db = module.get_session, db_module.get_session
    module.get_session = get_session
    db_module.get_session = get_session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield module.DatabaseStorage(), maker
    finally:
        module.get_session = original_module
        db_module.get_session = original_db
        await engine.dispose()


KEY = StorageKey(bot_id=1, chat_id=2, user_id=2)


def test_the_card_survives_a_restart():
    """Главная проверка: бот обновился, а карточка еды на месте.

    Раньше состояние жило в памяти процесса. Бот обновляется сам раз в
    полчаса — и человек, отвлёкшийся на минуту, жал «Сохранить» в пустоту.
    """
    async def scenario():
        async with storage() as (store, _):
            await store.set_state(KEY, FoodStates.confirming)
            await store.set_data(KEY, {"analysis": {"name": "Овсянка"}})

            # Перезапуск: прежний объект хранилища выброшен, база осталась.
            import services.fsm_storage as module
            fresh = module.DatabaseStorage()

            assert await fresh.get_state(KEY) == FoodStates.confirming.state
            assert (await fresh.get_data(KEY))["analysis"]["name"] == "Овсянка"
    run(scenario)


def test_clearing_really_clears():
    async def scenario():
        async with storage() as (store, _):
            await store.set_state(KEY, FoodStates.confirming)
            await store.set_data(KEY, {"a": 1})
            await store.set_state(KEY, None)
            await store.set_data(KEY, {})
            assert await store.get_state(KEY) is None
            assert await store.get_data(KEY) == {}
    run(scenario)


def test_an_unknown_conversation_is_simply_empty():
    async def scenario():
        async with storage() as (store, _):
            assert await store.get_state(KEY) is None
            assert await store.get_data(KEY) == {}
    run(scenario)


def test_a_broken_row_does_not_break_the_conversation():
    """Лучше начать заново, чем не отвечать вовсе."""
    async def scenario():
        async with storage() as (store, maker):
            await store.set_data(KEY, {"a": 1})
            async with maker() as session:
                row = (await session.execute(
                    __import__("sqlalchemy").select(FsmState))).scalars().one()
                row.data = "{это не json"
                await session.commit()
            assert await store.get_data(KEY) == {}
    run(scenario)


def test_two_people_do_not_share_a_conversation():
    async def scenario():
        async with storage() as (store, _):
            other = StorageKey(bot_id=1, chat_id=3, user_id=3)
            await store.set_data(KEY, {"кто": "первая"})
            await store.set_data(other, {"кто": "вторая"})
            assert (await store.get_data(KEY))["кто"] == "первая"
            assert (await store.get_data(other))["кто"] == "вторая"
    run(scenario)


def test_abandoned_conversations_are_forgotten():
    async def scenario():
        from datetime import datetime, timedelta, timezone

        import services.fsm_storage as module

        async with storage() as (store, _):
            await store.set_data(KEY, {"a": 1})
            fresh = datetime.now(timezone.utc)
            assert await module.forget_stale(now_utc=fresh) == 0

            later = fresh + timedelta(days=module.STALE_DAYS + 1)
            assert await module.forget_stale(now_utc=later) == 1
            assert await store.get_data(KEY) == {}
    run(scenario)


def test_the_daily_cleanup_also_forgets_abandoned_conversations():
    """Иначе таблица разговоров растёт вечно, а брошенная полгода назад
    анкета человеку уже не нужна."""
    import inspect

    import scheduler

    body = inspect.getsource(scheduler.clear_sent_marks)
    assert "forget_stale" in body
    assert inspect.iscoroutinefunction(scheduler.clear_sent_marks)
