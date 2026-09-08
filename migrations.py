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
# Расширение уже созданных колонок: (таблица, колонка, новый тип).
# SQLite длину строк не проверяет, а PostgreSQL проверяет — значение, которое
# спокойно легло в тесте, на сервере роняет заливку справочника.
# Разовые уборки данных: (таблица, колонка, что делаем).
# Выполняются при каждом запуске, но повторный проход ничего не меняет.
# Колонка указана не для красоты: на новой базе её может не быть вовсе —
# она осталась только у тех, кто ставил бота раньше. Уборка по несуществующей
# колонке валит запуск целиком, вместе с миграциями.
CLEANUPS: list[tuple[str, str, str]] = [
    ("meals", "photo_file_id",
     "UPDATE meals SET photo_file_id = NULL WHERE photo_file_id IS NOT NULL"),
]

COLUMN_WIDENINGS: list[tuple[str, str, str]] = [
    ("nutrition_preps", "fridge_days", "VARCHAR(60)"),
    ("nutrition_preps", "freezer_days", "VARCHAR(60)"),
]

# Индексы под самые частые запросы: «что человек ел сегодня», «сколько выпил».
# Одного индекса по user_id мало — база всё равно перебирает все записи
# человека за всё время, чтобы отобрать сегодняшние.
INDEXES: list[tuple[str, str, str]] = [
    ("ix_meals_user_logged", "meals", "(user_id, logged_at)"),
    ("ix_water_user_logged", "water_log", "(user_id, logged_at)"),
    ("ix_checkins_user_logged", "checkins", "(user_id, logged_at)"),
    ("ix_workout_log_user_done", "workout_log", "(user_id, completed_at)"),
    ("ix_dish_components_dish", "nutrition_dish_components", "(dish_id)"),
    ("ix_api_usage_day_kind", "api_usage", "(day, kind)"),
    ("ix_step_log_user_day", "step_log", "(user_id, day)"),
]

COLUMN_ADDITIONS: list[tuple[str, str, str]] = [
    ("nutrition_dishes", "prep_codes", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("nutrition_dishes", "estimated", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("nutrition_dishes", "no_cook", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("users", "timezone", "VARCHAR(64) NOT NULL DEFAULT 'Europe/Moscow'"),
    ("users", "last_app_open", "TIMESTAMP WITH TIME ZONE"),
    ("users", "last_bot_action", "TIMESTAMP WITH TIME ZONE"),
    ("notification_log", "variant", "VARCHAR(40) NOT NULL DEFAULT ''"),
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
    ("users", "reminders_enabled", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("subscriptions", "lifetime", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("nutrition_products", "tags", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("day_stats", "suggested", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ("day_stats", "world_open", "INTEGER NOT NULL DEFAULT 0"),
    ("day_stats", "bonus", "INTEGER NOT NULL DEFAULT 0"),
    ("day_stats", "bonus_codes", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("users", "daily_steps", "INTEGER"),
    ("users", "steps_token", "VARCHAR(32)"),
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

    applied += await _widen_columns(connection)
    applied += await _create_indexes(connection)
    applied += await _run_cleanups(connection)
    return applied


async def _run_cleanups(connection: AsyncConnection) -> list[str]:
    """Разовые уборки данных. Повторный запуск ничего не делает."""
    applied: list[str] = []
    for table, column, statement in CLEANUPS:
        existing = await connection.run_sync(_describe, table)
        # Ни таблицы, ни колонки может не быть — на свежей базе это норма.
        if existing is None or column not in existing:
            continue
        result = await connection.execute(text(statement))
        if result.rowcount:
            applied.append(f"{table}: очищено {result.rowcount}")
            logger.info("Уборка в %s: затронуто строк %s", table, result.rowcount)
    return applied


async def _create_indexes(connection: AsyncConnection) -> list[str]:
    """Создать недостающие индексы. Повторный запуск ничего не делает."""
    applied: list[str] = []
    for name, table, columns in INDEXES:
        existing = await connection.run_sync(_describe, table)
        # Как и с уборками: таблица может быть без нужной колонки, и тогда
        # создание индекса валит запуск вместе со всеми миграциями.
        needed = {part.strip() for part in columns.strip("()").split(",")}
        if existing is None or not needed <= existing:
            continue
        await connection.execute(
            text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {columns}")
        )
        applied.append(name)
    return applied


async def _widen_columns(connection: AsyncConnection) -> list[str]:
    """Расширить колонки, которым стало тесно.

    В SQLite тип VARCHAR(20) ничего не ограничивает, поэтому короткая колонка
    незаметна до первого запуска на PostgreSQL — там она роняет запись целиком.
    """
    applied: list[str] = []
    is_sqlite = connection.dialect.name == "sqlite"

    for table, column, definition in COLUMN_WIDENINGS:
        existing = await connection.run_sync(_describe, table)
        if existing is None or column not in existing:
            continue
        if is_sqlite:
            # SQLite длину не хранит и ALTER TYPE не умеет — там менять нечего.
            continue

        await connection.execute(
            text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {definition}")
        )
        applied.append(f"{table}.{column} → {definition}")
        logger.info("Расширена колонка %s.%s до %s", table, column, definition)

    return applied
