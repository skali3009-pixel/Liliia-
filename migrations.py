"""Мини-миграции: добавление колонок к уже существующим таблицам.

`create_all()` создаёт недостающие таблицы, но существующие не трогает.
Поэтому новое поле в модели ломает работающую базу: колонки нет, и любой
запрос к таблице падает. Здесь — список таких добавлений; применяются они
идемпотентно, повторный запуск ничего не портит.

Для серьёзных изменений схемы (переименование, смена типа, перенос данных)
нужен Alembic — этот модуль закрывает только добавление колонок.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

# (таблица, колонка, определение) — порядок соответствует истории изменений.
COLUMN_ADDITIONS: list[tuple[str, str, str]] = [
    ("users", "timezone", "VARCHAR(64) NOT NULL DEFAULT 'Europe/Moscow'"),
    ("progress_photos", "file_name", "VARCHAR(255)"),
    ("workouts", "program_code", "VARCHAR(50)"),
    ("workouts", "position", "INTEGER NOT NULL DEFAULT 0"),
    ("workouts", "muscle_group", "VARCHAR(60)"),
    ("workouts", "duration_minutes", "INTEGER"),
    ("workouts", "category", "VARCHAR(20) NOT NULL DEFAULT 'body'"),
    ("workouts", "style", "VARCHAR(20)"),
    ("meals", "fiber_g", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("users", "daily_fiber_g", "INTEGER"),
    ("body_measurements", "thigh_cm", "DOUBLE PRECISION"),
    ("users", "referral", "VARCHAR(64)"),
    ("users", "legal_version", "VARCHAR(20)"),
    ("users", "legal_accepted_at", "TIMESTAMP WITH TIME ZONE"),
    ("users", "marketing_consent", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def _describe(sync_connection, table: str) -> set[str] | None:
    """Колонки таблицы, либо None, если таблицы ещё нет."""
    inspector = inspect(sync_connection)
    if table not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns(table)}


async def apply_column_additions(connection: AsyncConnection) -> list[str]:
    """Добавить недостающие колонки. Возвращает список применённых изменений."""
    applied: list[str] = []

    for table, column, definition in COLUMN_ADDITIONS:
        existing = await connection.run_sync(_describe, table)
        if existing is None or column in existing:
            continue

        await connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        applied.append(f"{table}.{column}")
        logger.info("Добавлена колонка %s.%s", table, column)

    return applied
