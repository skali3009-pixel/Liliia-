"""Асинхронное подключение к PostgreSQL через SQLAlchemy 2.0."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config

engine = create_async_engine(config.DATABASE_URL, echo=False, future=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Контекстный менеджер сессии БД: `async with get_session() as session:`."""
    async with async_session_maker() as session:
        yield session


async def init_models() -> None:
    """Создать таблицы в БД, если их ещё нет.

    Годится для разработки и первого запуска. Для продакшена и последующих
    изменений схемы — миграции (например, Alembic), а не auto-create.
    """
    from models import Base  # локальный импорт: гарантирует, что все модели уже загружены

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
