"""Асинхронное подключение к PostgreSQL через SQLAlchemy 2.0."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config

logger = logging.getLogger(__name__)

# Настройки пула. По умолчанию SQLAlchemy держит 5 соединений и до 10
# сверх того — этого мало, когда людей становится много, и запросы начинают
# ждать очереди. pool_pre_ping спасает от «протухших» соединений: после
# ночного простоя или перезапуска PostgreSQL первое обращение иначе падает
# с ошибкой вместо ответа.
_POOL = dict(pool_size=20, max_overflow=30, pool_timeout=30,
             pool_recycle=1800, pool_pre_ping=True)
# У SQLite (тесты, стенд) пула нет — настройки к нему неприменимы.
_IS_SQLITE = config.DATABASE_URL.startswith("sqlite")

engine = create_async_engine(config.DATABASE_URL, echo=False, future=True,
                             **({} if _IS_SQLITE else _POOL))
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Контекстный менеджер сессии БД: `async with get_session() as session:`."""
    async with async_session_maker() as session:
        yield session


async def init_models() -> None:
    """Создать недостающие таблицы и дописать новые колонки в существующие.

    create_all() сам по себе не меняет уже созданные таблицы, поэтому после
    него применяются мини-миграции — иначе новое поле в модели ломает
    работающую базу.
    """
    from migrations import apply_column_additions
    from models import Base  # локальный импорт: гарантирует, что все модели уже загружены

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        applied = await apply_column_additions(conn)

    if applied:
        logger.info("Схема БД обновлена: %s", ", ".join(applied))

    # Заливка справочников не должна мешать боту запуститься. Если данные
    # почему-то не легли, лучше работать без части справочника, чем не
    # работать вовсе: человек и так может вести дневник и смотреть прогресс.
    from seed.loader import seed_workouts
    from seed.nutrition.loader import seed_nutrition

    for name, seeder in (("упражнения", seed_workouts), ("питание", seed_nutrition)):
        try:
            async with async_session_maker() as session:
                await seeder(session)
        except Exception:
            logger.exception("Не удалось залить справочник «%s» — бот работает без него",
                             name)
