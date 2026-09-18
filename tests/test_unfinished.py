"""Незаконченная анкета: счётчик вопросов, возврат и письмо на следующий день.

Лилия заметила, что многие ставят бота и не доходят до конца анкеты. Дыра
оказалась глубже, чем «скучно отвечать»: и напоминания, и письма вернувшимся
отбирают людей по `onboarding_completed = True`, то есть застрявший на
четвёртом вопросе не получал от бота больше ничего и никогда. А `/start` —
кнопка, которую Telegram сам подсовывает, — стирал ответы и начинал с первого
вопроса.

Здесь проверяется не текст писем, а три вещи, каждая из которых возвращает
поломку молча: счётчик считает по настоящему списку вопросов, возврат не
стирает ответы, и письмо не уходит тем, кто нам этого не разрешал.
"""

import asyncio
import contextlib
import datetime as dt
from pathlib import Path

import pytest
from aiogram.fsm.storage.base import StorageKey
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from handlers import onboarding as O
from models import Base, FsmState, User
from services import unfinished
from services.fsm_storage import _key
from states.onboarding import OnboardingStates

КОРЕНЬ = Path(__file__).resolve().parent.parent
ИСХОДНИК = (КОРЕНЬ / "handlers" / "onboarding.py").read_text(encoding="utf-8")

# 12:00 по Москве — тот час, в который уходят письма.
ПОЛДЕНЬ = dt.datetime(2026, 9, 18, 9, 0, tzinfo=dt.timezone.utc)


class ФейковоеСообщение:
    def __init__(self):
        self.отправлено = []

    async def answer(self, текст, reply_markup=None, **_):
        кнопки = []
        if reply_markup is not None:
            for ряд in reply_markup.inline_keyboard:
                кнопки += [(к.text, к.callback_data) for к in ряд]
        self.отправлено.append((текст, кнопки))


def run(scenario):
    asyncio.run(scenario())


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        yield session
    await engine.dispose()


def человек(uid, **поля):
    вчера = ПОЛДЕНЬ - dt.timedelta(days=1)
    поля.setdefault("timezone", "Europe/Moscow")
    поля.setdefault("legal_accepted_at", вчера)
    поля.setdefault("last_bot_action", вчера)
    return User(id=uid, full_name=f"Гостья {uid}", **поля)


# --- Вопросы написаны один раз ---------------------------------------------

def test_вопрос_не_написан_дважды():
    """Вторая копия вопроса — это вопрос, который человек увидит не тот.

    Счётчик и возврат берут текст из списка ШАГИ. Если тот же вопрос останется
    написанным словами внутри обработчика, однажды поправят одну копию, и
    вернувшийся в анкету человек прочтёт старую.
    """
    for шаг in O.ШАГИ:
        первая_строка = шаг.текст.split("\n")[0][:30]
        assert ИСХОДНИК.count(первая_строка) == 1, шаг.текст[:40]


def test_счётчик_считает_по_настоящему_списку():
    """«Вопрос 7 из 9», а за ним ещё четыре — так бывает, когда число вписано руками."""
    assert O.ВСЕГО_ШАГОВ == len(O.ШАГИ) == 9
    assert [O.номер_шага(ш) for ш in O.ШАГИ] == list(range(1, 10))

    async def scenario():
        м = ФейковоеСообщение()
        await O.спросить(м, O.ШАГИ[2])
        текст = м.отправлено[0][0]
        assert текст.startswith("Вопрос 3 из 9")
        assert O.ШАГИ[2].текст in текст
    run(scenario)


def test_итог_не_вписан_числом(monkeypatch):
    """Убери вопрос — счётчик обязан поехать следом, а не остаться «из 9».

    Проверяется поведением, а не поиском числа в исходнике: искать «из 9»
    словами значит ловить собственные комментарии, что и вышло с первого раза.
    """
    async def scenario():
        monkeypatch.setattr(O, "ШАГИ", O.ШАГИ[:4])
        monkeypatch.setattr(O, "ВСЕГО_ШАГОВ", 4)
        м = ФейковоеСообщение()
        await O.спросить(м, O.ШАГИ[1])
        assert м.отправлено[0][0].startswith("Вопрос 2 из 4")

        возврат = ФейковоеСообщение()
        await O.предложить_продолжить(возврат, O.ШАГИ[1])
        assert "2 из 4" in возврат.отправлено[0][0]
    run(scenario)


def test_у_каждого_шага_своё_состояние():
    """Два вопроса на одном состоянии — это потерянный ответ."""
    состояния = [ш.состояние.state for ш in O.ШАГИ]
    assert len(set(состояния)) == len(состояния)
    assert set(O.ПО_СОСТОЯНИЮ) == set(состояния)


# --- Возврат в анкету ------------------------------------------------------

def test_start_не_стирает_ответы():
    """Раньше /start возвращал к первому вопросу — пять ответов пропадали молча."""
    до_возврата = ИСХОДНИК.split("предложить_продолжить(message, шаг)", 1)[0]
    хвост = до_возврата.split("if completed:", 1)[1]
    # Только код: рассказать в комментарии, что тут когда-то стоял clear(),
    # не запрещено, а сторож, ловящий собственное объяснение, бесполезен.
    код = "\n".join(с for с in хвост.splitlines() if not с.strip().startswith("#"))
    assert "state.clear()" not in код, "состояние стирается до предложения продолжить"


def test_возврат_предлагает_именно_тот_вопрос():
    async def scenario():
        м = ФейковоеСообщение()
        шаг = O.ПО_СОСТОЯНИЮ[OnboardingStates.target_weight.state]
        await O.предложить_продолжить(м, шаг)

        текст, кнопки = м.отправлено[0]
        assert "5 из 9" in текст and "Осталось 5" in текст
        assert [к[0] for к in кнопки] == ["Продолжить", "Начать заново"]
        assert кнопки[0][1] == O.CB_RESUME
    run(scenario)


def test_кнопка_в_письме_та_же_что_в_чате():
    """Два способа вернуться в анкету разошлись бы между собой молча."""
    from keyboards.notifications import unfinished_keyboard

    ряды = unfinished_keyboard().inline_keyboard
    assert ряды[0][0].callback_data == O.CB_RESUME


# --- Кому уходит письмо ----------------------------------------------------

def test_письмо_застрявшей_на_середине():
    async def scenario():
        async with db() as session:
            session.add(человек(1))
            session.add(FsmState(
                key=_key(StorageKey(bot_id=7, chat_id=1, user_id=1)),
                state=OnboardingStates.current_weight.state, data="{}"))
            await session.commit()

            письма = await unfinished.due(session, now_utc=ПОЛДЕНЬ)
            assert [(п.user_id, п.step) for п in письма] == [(1, 4)]
            assert "4 из 9" in письма[0].text
    run(scenario)


# Рядом с каждым, кому писать нельзя, обязательно сидит та, кому можно, — и
# в том же часовом поясе. Без неё поясов не находится вовсе, выборка
# возвращается пустой на первом же запросе, и проверка проходит на коде, где
# второй запрет снят. Поймано поломкой: убрала фильтр — тесты не заметили.
def _не_пишем(**поля):
    async def scenario():
        async with db() as session:
            session.add(человек(1, **поля))
            session.add(человек(2))          # ей письмо положено
            await session.commit()
            письма = await unfinished.due(session, now_utc=ПОЛДЕНЬ)
            assert [п.user_id for п in письма] == [2], поля
    run(scenario)


def test_без_согласия_не_пишем_вовсе():
    """Не согласился с условиями — писать ему мы не вправе, и польза этого не отменяет."""
    _не_пишем(legal_accepted_at=None)


def test_дошедшей_до_конца_не_пишем():
    _не_пишем(onboarding_completed=True)


def test_выключившей_напоминания_не_пишем():
    _не_пишем(reminders_enabled=False)


def test_письмо_ровно_на_следующий_день_и_один_раз():
    """Сегодня — рано, послезавтра — уже выпрашивание."""
    async def scenario():
        for молчит, ждём in ((0, 0), (1, 1), (2, 0), (7, 0), (30, 0)):
            async with db() as session:
                когда = ПОЛДЕНЬ - dt.timedelta(days=молчит)
                session.add(человек(1, last_bot_action=когда))
                await session.commit()
                письма = await unfinished.due(session, now_utc=ПОЛДЕНЬ)
                assert len(письма) == ждём, молчит
    run(scenario)


def test_не_в_свой_час_молчим():
    """Письмо уходит в местный полдень, а не когда планировщик проснулся."""
    async def scenario():
        async with db() as session:
            session.add(человек(1))
            await session.commit()
            для_утра = ПОЛДЕНЬ - dt.timedelta(hours=3)
            assert await unfinished.due(session, now_utc=для_утра) == []
    run(scenario)


# --- Что в письме ----------------------------------------------------------

def test_в_письме_нет_упрёка_и_цифр_про_тело():
    """Человек ничего нам не обещал, и «ты не ответила» — это счёт, а не помощь."""
    import re

    упрёки = ("не ответил", "не закончил", "не дошл", "забыл", "бросил",
              "почему ты", "всё ещё не", "напоминаю")
    for шаг in (0, 1, 5, 9):
        текст = unfinished.render(шаг, O.ВСЕГО_ШАГОВ).lower()
        for слово in упрёки:
            assert слово not in текст, (шаг, слово)
        # Цифр про тело быть не должно вовсе: ни веса, ни съеденного.
        assert not re.search(r"\d+\s*(кг|ккал|мл|г\b)", текст), шаг


def test_без_известного_шага_номер_не_выдумывается():
    """Состояние протухло — врать про «вопрос 4» нельзя, звать всё равно надо."""
    import re

    текст = unfinished.render(0, O.ВСЕГО_ШАГОВ)
    assert "остановилась на вопросе" not in текст.lower()
    assert not re.search(r"вопросе \d+", текст.lower())
    assert "9 коротких вопросов" in текст


def test_номер_шага_берётся_из_анкеты_а_не_из_второй_таблицы():
    """Второй справочник «какой вопрос какой по счёту» разошёлся бы в первый же день."""
    исходник = (КОРЕНЬ / "services" / "unfinished.py").read_text(encoding="utf-8")
    assert "ПО_СОСТОЯНИЮ" in исходник and "номер_шага" in исходник
    for имя in ("gender", "current_weight", "allergies"):
        assert f'"{имя}"' not in исходник, имя


# --- Рассылка подключена ---------------------------------------------------

def test_рассылка_стоит_в_планировщике():
    """Служба, которую никто не зовёт, — это файл, а не письмо."""
    расписание = (КОРЕНЬ / "scheduler.py").read_text(encoding="utf-8")
    assert "unfinished.due(session)" in расписание
    assert 'id="unfinished"' in расписание
    # И не чаще одного письма на человека за день.
    кусок = расписание.split("async def send_unfinished", 1)[1].split("\nasync def")[0]
    assert '"unfinished")' in кусок and "_already_sent" in кусок
