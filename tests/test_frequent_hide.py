"""«Ешь как обычно»: убрать лишнее — и подсказки, которые показывают один раз.

Две жалобы Лилии, разные по природе.

Первая: в списке частой еды есть «плюс», чтобы записать повторно, и нет
ничего, чтобы убрать. «Съела скитлс дважды — не факт, что съем в третий»:
список умеет только копить, и случайные конфеты навсегда встают между
овсянкой и кофе.

Вторая: подсказка по вкладке приходила при каждом заходе. Она нужна один
раз — в первый. Память о показанном жила в браузере телефона, а внутри
Telegram он забывает; и отмечалась она только после последней карточки или
«Пропустить» — то есть у всех, кто закрыл приложение раньше, тур начинался
заново, и так всегда.

Проверяется здесь то, что в обоих случаях ломается молча: что скрытие не
трогает дневник, что вернуть убранное можно, и что память о подсказке
живёт на сервере, а не на устройстве.
"""

import asyncio
import contextlib
import datetime as дата
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (Base, Meal, MealSourceEnum, MealTypeEnum, User)
from services import favorites, tours

КОРЕНЬ = Path(__file__).resolve().parent.parent
ПРИЛОЖЕНИЕ = (КОРЕНЬ / "webapp" / "static" / "app.js").read_text(encoding="utf-8")

ОНА = 700


def run(scenario):
    return asyncio.run(scenario())


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(id=ОНА, full_name="Лилия", timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


async def поела(session, имя, раз=3):
    сейчас = дата.datetime.now()
    for номер in range(раз):
        session.add(Meal(user_id=ОНА, name=имя, weight_g=100, calories=200,
                         protein_g=5, fat_g=5, carbs_g=20, fiber_g=1,
                         meal_type=MealTypeEnum.SNACK, source=MealSourceEnum.TEXT,
                         logged_at=сейчас - дата.timedelta(hours=номер + 1)))
    await session.commit()


async def список(session):
    пользователь = await session.get(User, ОНА)
    еда = await favorites.frequent_meals(
        session, ОНА, timezone_name="Europe/Moscow",
        hidden=favorites.hidden_names(пользователь))
    return [позиция.name for позиция in еда]


# --- Убрать из списка ------------------------------------------------------

def test_убранное_больше_не_предлагается():
    async def scenario():
        async with db() as session:
            await поела(session, "Овсянка")
            await поела(session, "Skittles")
            assert set(await список(session)) == {"Овсянка", "Skittles"}

            пользователь = await session.get(User, ОНА)
            assert await favorites.hide(session, пользователь, "Skittles") is True
            assert await список(session) == ["Овсянка"]
    run(scenario)


def test_убранное_остаётся_в_дневнике():
    """Человек просил не предлагать блюдо, а не забыть, что он его ел.

    Стереть записи заодно было бы тихой потерей: кольца, статистика и
    история за прошлые дни изменились бы задним числом, и никто бы не понял,
    почему вчерашний день вдруг стал другим.
    """
    async def scenario():
        async with db() as session:
            await поела(session, "Skittles")
            пользователь = await session.get(User, ОНА)
            await favorites.hide(session, пользователь, "Skittles")

            съедено = (await session.execute(
                select(Meal).where(Meal.name == "Skittles")
            )).scalars().all()
            assert len(съедено) == 3
            assert sum(еда.calories for еда in съедено) == 600
    run(scenario)


def test_убирается_по_смыслу_а_не_по_написанию():
    """«Skittles», «skittles» и «Skittles » — одно блюдо, как и в самом списке."""
    async def scenario():
        async with db() as session:
            await поела(session, "Skittles")
            await поела(session, " skittles ")
            пользователь = await session.get(User, ОНА)
            await favorites.hide(session, пользователь, "SKITTLES")
            assert await список(session) == []
    run(scenario)


def test_убрать_дважды_не_плодит_записей():
    async def scenario():
        async with db() as session:
            пользователь = await session.get(User, ОНА)
            assert await favorites.hide(session, пользователь, "Skittles") is True
            assert await favorites.hide(session, пользователь, "skittles") is False
            assert favorites.hidden_names(пользователь) == {"skittles"}
    run(scenario)


def test_пустое_имя_не_убирает_ничего():
    async def scenario():
        async with db() as session:
            пользователь = await session.get(User, ОНА)
            for мусор in ("", "   ", None):
                assert await favorites.hide(session, пользователь, мусор) is False
            assert favorites.hidden_names(пользователь) == set()
    run(scenario)


def test_убранное_можно_вернуть():
    """Промахнуться по маленькой кнопке легко, а список без возврата врёт навсегда."""
    async def scenario():
        async with db() as session:
            await поела(session, "Овсянка")
            await поела(session, "Skittles")
            пользователь = await session.get(User, ОНА)
            await favorites.hide(session, пользователь, "Skittles")
            await favorites.hide(session, пользователь, "Овсянка")
            assert await список(session) == []

            assert await favorites.restore(session, пользователь) == 2
            assert set(await список(session)) == {"Овсянка", "Skittles"}
            assert await favorites.restore(session, пользователь) == 0
    run(scenario)


def test_кнопка_убрать_спрашивает_точно():
    """Кнопка стоит рядом с «записать» и мала — без вопроса промах стирал бы молча."""
    кусок = ПРИЛОЖЕНИЕ.split("const hide = document.createElement", 1)[1] \
                       .split("wrap.append", 1)[0]
    assert "askYes(" in кусок
    assert "'/api/frequent'" in кусок


def test_строка_возврата_появляется_только_когда_есть_что_возвращать():
    кусок = ПРИЛОЖЕНИЕ.split("function renderFrequent", 1)[1].split("\n}", 1)[0]
    assert "back.hidden = !hiddenCount" in кусок


# --- Подсказки показываются один раз ---------------------------------------

def test_показанное_помнится_на_сервере():
    async def scenario():
        async with db() as session:
            пользователь = await session.get(User, ОНА)
            assert tours.seen(пользователь) == []
            assert await tours.mark(session, пользователь, "world") is True
            assert tours.seen(пользователь) == ["world"]

            свежий = await session.get(User, ОНА)
            assert tours.seen(свежий) == ["world"]
    run(scenario)


def test_один_экран_отмечается_один_раз():
    async def scenario():
        async with db() as session:
            пользователь = await session.get(User, ОНА)
            await tours.mark(session, пользователь, "today")
            assert await tours.mark(session, пользователь, "today") is False
            assert tours.seen(пользователь) == ["today"]
    run(scenario)


def test_чужой_экран_в_память_не_пишется():
    """Строка в базе не резиновая, а список вкладок закрытый."""
    async def scenario():
        async with db() as session:
            пользователь = await session.get(User, ОНА)
            assert await tours.mark(session, пользователь, "вкладка-которой-нет") is False
            assert await tours.mark(session, пользователь, "") is False
            assert tours.seen(пользователь) == []
    run(scenario)


def test_подсказки_можно_вернуть_все():
    async def scenario():
        async with db() as session:
            пользователь = await session.get(User, ОНА)
            for экран in tours.SCREENS:
                await tours.mark(session, пользователь, экран)
            assert tours.seen(пользователь) == list(tours.SCREENS)

            await tours.forget(session, пользователь)
            assert tours.seen(пользователь) == []
    run(scenario)


def test_отметка_ставится_при_показе_а_не_в_конце():
    """Дощёлкать до последней карточки человек не обязан.

    Пока отметка стояла только в конце, закрывшая приложение на первом шаге
    видела тур снова. И снова. Это и была жалоба.
    """
    кусок = ПРИЛОЖЕНИЕ.split("function startTour", 1)[1].split("\n}", 1)[0]
    # Смотреть надо на ветку, где тур правда показывается. Рядом стоит вторая
    # отметка — «показывать нечего, все блоки скрыты», — и проверка «есть ли
    # где-то в функции rememberTour» спокойно проходила на коде, где отметку
    # при показе убрали. Поймано поломкой.
    показ = кусок.split("tourAt = 0", 1)[1].split("showTourStep", 1)[0]
    assert "rememberTour(screen)" in показ


def test_память_о_подсказках_не_только_в_браузере():
    """Внутри Telegram память телефона переживает не всякое закрытие приложения."""
    кусок = ПРИЛОЖЕНИЕ.split("function rememberTour", 1)[1].split("\n}", 1)[0]
    assert "'/api/tours'" in кусок

    # И обратно: ответ сервера обязан подставляться при загрузке экрана.
    assert "tourFromServer(data.tours)" in ПРИЛОЖЕНИЕ
    забыть = ПРИЛОЖЕНИЕ.split("function forgetTours", 1)[1].split("\n}", 1)[0]
    assert "'/api/tours'" in забыть and "forget" in забыть
