"""Короткая анкета: что спрашиваем до нормы и что после.

Анкету сократили с девяти вопросов до семи. Правило простое: до нормы
спрашиваем только то, без чего её не посчитать. Целевой вес и аллергии в
расчёт не входят — их предлагаем после, когда человек уже получил, ради чего
отвечал, и может спокойно не отвечать.

Проверяется здесь не «работает ли анкета» — это видно и так, — а три тихие
поломки.

Первая: последний шаг стал кнопкой, а у сообщения с кнопкой автор — бот. Возьми
код автора оттуда, и профиль запишется боту: человек ответит на семь вопросов и
останется без анкеты, без единой ошибки на экране.

Вторая: обработчики убранных вопросов. В базе живут незаконченные разговоры, и
в момент обновления кто-то стоит ровно в убранном шаге. Уберёшь обработчик — и
его ответ не примет никто.

Третья: предложение после нормы не должно превращаться во вторую анкету —
ни своей записи, ни своей проверки, ни кнопки «потом», которая ничего не меняет.
"""

import asyncio
import contextlib

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import datetime as дата

import db as db_module
from handlers import legal as L
from handlers import onboarding as O
from keyboards.profile import CB_EDIT
from models import Base, GoalEnum, User
from states.onboarding import OnboardingStates

ОНА = 500
БОТ = 777


class Человек:
    """То, что аиограм кладёт в from_user."""

    def __init__(self, uid=ОНА, full_name="Лилия Скалий"):
        self.id, self.username, self.full_name = uid, "lilia", full_name


class ФейковоеСообщение:
    """Сообщение в чате. Автор — бот: именно так приходит нажатие кнопки."""

    def __init__(self, чат, text="", автор=None):
        self.чат, self.text = чат, text
        self.from_user = автор or Человек(БОТ, "AURA")

    async def answer(self, текст, reply_markup=None, **_):
        кнопки = []
        if reply_markup is not None and getattr(reply_markup, "inline_keyboard", None):
            for ряд in reply_markup.inline_keyboard:
                кнопки += [(к.text, к.callback_data) for к in ряд]
        self.чат.append((текст, кнопки))

    async def answer_photo(self, *a, **k): pass
    async def answer_video_note(self, *a, **k): pass
    async def edit_text(self, *a, **k): pass


class ФейковаяКнопка:
    def __init__(self, чат, data):
        self.data = data
        self.message = ФейковоеСообщение(чат)
        self.from_user = Человек()

    async def answer(self, *a, **k): pass


def run(scenario):
    return asyncio.run(scenario())


@contextlib.asynccontextmanager
async def стенд(monkeypatch):
    """Живая база и подменённые сессии — анкета пишет по-настоящему."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def сессия():
        async with maker() as s:
            yield s

    monkeypatch.setattr(db_module, "get_session", сессия)
    monkeypatch.setattr(O, "get_session", сессия)

    async with maker() as s:
        s.add(User(id=ОНА, full_name="Лилия Скалий"))
        await s.commit()
    try:
        yield maker
    finally:
        await engine.dispose()


def контекст():
    return FSMContext(MemoryStorage(),
                      StorageKey(bot_id=1, chat_id=ОНА, user_id=ОНА))


async def пройти(чат, st, *, цель="lose_weight", застрять=None, ответ=""):
    """Пройти анкету целиком. `застрять` подсаживает в убранный вопрос."""
    await O.begin_onboarding(ФейковоеСообщение(чат), st, ОНА)
    await O.process_gender(ФейковаяКнопка(чат, "onb_gender:female"), st)
    await O.process_age(ФейковоеСообщение(чат, "31", Человек()), st)
    await O.process_height(ФейковоеСообщение(чат, "168", Человек()), st)
    await O.process_current_weight(ФейковоеСообщение(чат, "63.5", Человек()), st)

    if застрять == "target_weight":
        await st.set_state(OnboardingStates.target_weight)
        await O.process_target_weight(ФейковоеСообщение(чат, ответ, Человек()), st)

    await O.process_activity(ФейковаяКнопка(чат, "onb_activity:moderate"), st)
    await O.process_goal(ФейковаяКнопка(чат, f"onb_goal:{цель}"), st)

    if застрять == "allergies":
        await st.update_data(diet_type="regular")
        await st.set_state(OnboardingStates.allergies)
        await O.process_allergies(ФейковоеСообщение(чат, ответ, Человек()), st)
        return
    await O.process_diet_type(ФейковаяКнопка(чат, "onb_diet:regular"), st)


# --- Профиль достаётся человеку, а не боту --------------------------------

def test_анкета_записывается_человеку_а_не_автору_сообщения(monkeypatch):
    """Последний шаг — кнопка, а у сообщения с кнопкой автор бот.

    Возьми код автора оттуда — и профиль запишется боту. На экране при этом
    не будет ни одной ошибки: норма посчитается, поздравление придёт, а
    человек останется без анкеты навсегда.
    """
    async def scenario():
        async with стенд(monkeypatch) as maker:
            await пройти([], контекст())
            async with maker() as s:
                она = await s.get(User, ОНА)
                бот = await s.get(User, БОТ)
                assert она.onboarding_completed is True
                assert она.daily_calories and она.daily_water_ml
                assert она.full_name == "Лилия Скалий"
                assert бот is None, "профиль записался автору сообщения"
    run(scenario)


def test_подруге_называют_новенькую_а_не_бота(monkeypatch):
    """«AURA завела профиль по твоей ссылке» — та же ошибка, другим боком."""
    async def scenario():
        письма = []

        class Почта:
            async def send_message(self, chat_id, text):
                письма.append((chat_id, text))

        сообщение = ФейковоеСообщение([])
        сообщение.bot = Почта()
        await O._thank_for_invite(сообщение, Человек(ОНА, "Мария Иванова"), 42, 7, 0)
        assert письма and письма[0][1].startswith("Мария")
    run(scenario)


def test_start_доходит_до_первого_вопроса(monkeypatch):
    """Самый первый шаг живого человека — и ни один тест его не трогал.

    Проверка появилась после настоящей поломки: правка «брать человека, а не
    автора сообщения» заменила два места вместо одного и увела в `cmd_start`
    имя, которого там нет. Анкета, норма и предложение при этом работали
    прекрасно — падало бы только само «Начать», то есть у каждого нового
    человека и сразу.
    """
    async def scenario():
        async with стенд(monkeypatch) as maker:
            чат = []
            сообщение = ФейковоеСообщение(чат, "/start", Человек())
            монета = type("C", (), {"args": None})()
            async with maker() as s:
                гостья = await s.get(User, ОНА)
                гостья.legal_version = L.LEGAL_VERSION
                гостья.legal_accepted_at = дата.datetime.now(дата.timezone.utc)
                await s.commit()

            await O.cmd_start(сообщение, контекст(), монета)
            весь = "\n".join(т for т, _ in чат)
            assert "Вопрос 1 из" in весь, весь
    run(scenario)


def test_каждый_убранный_шаг_остался_подключённым():
    """Функция цела, а обработчик снят с состояния — и ответ не примет никто.

    Прежний тест звал функцию напрямую и такой поломки не видел вовсе:
    декоратор при прямом вызове не участвует. Смотрим на то, что аиограм
    правда зарегистрировал.
    """
    подключены = set()
    for обработчик in O.router.message.handlers:
        for фильтр in обработчик.filters:
            состояние = getattr(фильтр.callback, "state", None)
            if состояние:
                подключены.add(состояние)

    for убранный in (OnboardingStates.target_weight, OnboardingStates.allergies):
        assert убранный.state in подключены, убранный.state


# --- Что спрашиваем до нормы ----------------------------------------------

def test_целевой_вес_и_аллергии_до_нормы_не_спрашивают(monkeypatch):
    async def scenario():
        async with стенд(monkeypatch) as maker:
            чат = []
            await пройти(чат, контекст())
            до_нормы = "\n".join(т for т, _ in чат).split("Профиль настроен")[0]
            assert "вес хочешь в итоге" not in до_нормы
            assert "аллерги" not in до_нормы.lower()

            async with maker() as s:
                она = await s.get(User, ОНА)
                assert она.target_weight_kg is None and она.allergies is None
    run(scenario)


# --- Что предлагаем после -------------------------------------------------

def _предложение(чат):
    return next((пара for пара in reversed(чат) if "необязательн" in пара[0]), None)


def test_после_нормы_предлагают_то_что_убрали(monkeypatch):
    async def scenario():
        async with стенд(monkeypatch) as maker:
            чат = []
            await пройти(чат, контекст(), цель="lose_weight")

            текст, кнопки = _предложение(чат)
            assert [д for _, д in кнопки] == [f"{CB_EDIT}target_weight",
                                              f"{CB_EDIT}allergies"]
            # Предложение стоит после нормы, а не до неё.
            весь = [т for т, _ in чат]
            assert весь.index(текст) > next(
                i for i, т in enumerate(весь) if "Профиль настроен" in т)
    run(scenario)


def test_бесполезного_не_спрашивают(monkeypatch):
    """У поддержания число на весах не финиш — «цель по весу» там пустой вопрос."""
    async def scenario():
        async with стенд(monkeypatch) as maker:
            чат = []
            await пройти(чат, контекст(), цель="maintain")
            _, кнопки = _предложение(чат)
            assert [д for _, д in кнопки] == [f"{CB_EDIT}allergies"]
    run(scenario)


def test_уже_известного_не_переспрашивают(monkeypatch):
    """Ответила в прежнем шаге — значит, ответ есть, и спрашивать второй раз незачем."""
    async def scenario():
        async with стенд(monkeypatch) as maker:
            чат = []
            await пройти(чат, контекст(), застрять="target_weight", ответ="58")
            _, кнопки = _предложение(чат)
            assert [д for _, д in кнопки] == [f"{CB_EDIT}allergies"]

            async with maker() as s:
                assert (await s.get(User, ОНА)).target_weight_kg == 58.0
    run(scenario)


def test_у_предложения_нет_кнопки_потом(monkeypatch):
    """Кнопка, которая ничего не меняет, учит, что бота можно не слушать."""
    async def scenario():
        async with стенд(monkeypatch) as maker:
            чат = []
            await пройти(чат, контекст())
            _, кнопки = _предложение(чат)
            for подпись, _ in кнопки:
                assert "потом" not in подпись.lower() and "позже" not in подпись.lower()
    run(scenario)


def test_предложение_не_заводит_второй_записи():
    """Сохраняет и проверяет ответ прежний код профиля, а не копия рядом."""
    from pathlib import Path

    исходник = (Path(__file__).resolve().parent.parent / "handlers" /
                "onboarding.py").read_text(encoding="utf-8")
    кусок = исходник.split("async def _offer_the_rest", 1)[1].split("\nasync def")[0]
    assert CB_EDIT.rstrip(":") in кусок or "CB_EDIT" in кусок
    for запрещено in ("set_target_weight", "set_allergies", "session.commit"):
        assert запрещено not in кусок, запрещено


# --- Застрявшие в убранных вопросах ---------------------------------------

@pytest.mark.parametrize("шаг, ответ, поле, значение", [
    ("target_weight", "58", "target_weight_kg", 58.0),
    ("allergies", "орехи", "allergies", "орехи"),
])
def test_ответ_в_убранном_вопросе_принимается(monkeypatch, шаг, ответ, поле, значение):
    """В базе живут незаконченные разговоры: кто-то стоит в убранном шаге.

    Убери обработчик — и человек, набравший ответ, не получит ничего: его
    сообщение съест сценарий, а следующего вопроса не будет.
    """
    async def scenario():
        async with стенд(monkeypatch) as maker:
            await пройти([], контекст(), застрять=шаг, ответ=ответ)
            async with maker() as s:
                она = await s.get(User, ОНА)
                assert она.onboarding_completed is True
                assert getattr(она, поле) == значение
    run(scenario)
