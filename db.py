"""Асинхронное подключение к PostgreSQL через SQLAlchemy 2.0."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config

logger = logging.getLogger(__name__)

engine = create_async_engine(config.DATABASE_URL, echo=False, future=True)
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

    # Библиотека упражнений нужна сразу — без неё раздел тренировок пустой.
    from seed.loader import seed_workouts

    async with async_session_maker() as session:
        await seed_workouts(session)
