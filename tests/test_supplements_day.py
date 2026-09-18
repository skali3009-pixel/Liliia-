"""Приём добавки и список на сегодня считают день одним способом.

Поймано живым прогоном: тест про добавки упал один раз из многих, ровно в
21:00 UTC — это полночь в часовом поясе тестового человека. Отметка о приёме
спрашивала сутки у `day_bounds` сама, а список — через `user_today`. В
обычный час оба дают одно и то же, а на границе суток расходятся: отметка
ложится в один день, список читает другой, и человек видит, что приём
«не записался».

Здесь проверяется само свойство, а не совпадение по часам: обе стороны
обязаны брать день из одного места. Полночь по заказу не наступает, поэтому
день подменяется — и видно, в какие сутки отметка на самом деле смотрит.
"""

import asyncio
import contextlib
import datetime as дата

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, Supplement, SupplementLog, User
from services import supplements as служба
from utils.timeframe import today_in

ОНА = 900
ПОЯС = "Europe/Moscow"


def run(scenario):
    return asyncio.run(scenario())


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add(User(id=ОНА, full_name="Лилия", timezone=ПОЯС))
        session.add(Supplement(user_id=ОНА, name="Витамин D", schedule_type="daily"))
        await session.commit()
        yield session
    await engine.dispose()


def test_отметка_смотрит_в_тот_же_день_что_и_список(monkeypatch):
    """Отметка ищет прежнюю запись в сутках, которые назвал `user_today`.

    Подменяем «сегодня» на вчера. Если отметка берёт день оттуда же, откуда
    список, она найдёт вчерашнюю запись и перепишет её — записей останется
    одна. Если она спрашивает часы сама, то не найдёт ничего и заведёт
    вторую: один и тот же приём окажется отмечен дважды.
    """
    async def scenario():
        async with db() as session:
            добавка = (await session.execute(select(Supplement))).scalar_one()
            вчера = today_in(ПОЯС) - дата.timedelta(days=1)

            # Вчерашний приём, отмеченный вчера.
            session.add(SupplementLog(
                supplement_id=добавка.id, user_id=ОНА, skipped=False,
                logged_at=дата.datetime.now(дата.timezone.utc) - дата.timedelta(days=1)))
            await session.commit()

            monkeypatch.setattr(служба, "user_today", lambda _tz: вчера)
            await служба.mark(session, user_id=ОНА, supplement_id=добавка.id,
                              skipped=True, timezone_name=ПОЯС)

            записей = (await session.execute(select(SupplementLog))).scalars().all()
            assert len(записей) == 1, "отметка завела вторую запись за те же сутки"
            assert записей[0].skipped is True
    run(scenario)
