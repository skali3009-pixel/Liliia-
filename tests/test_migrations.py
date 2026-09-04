"""Тесты мини-миграций: новое поле не должно ломать работающую базу."""

import asyncio

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from migrations import apply_column_additions


def _columns(sync_connection, table):
    return {c["name"] for c in inspect(sync_connection).get_columns(table)}


def test_missing_column_is_added_and_rerun_is_safe():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            # Старая таблица — такая, какой она была до появления часового пояса.
            await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, age INTEGER)"))

            applied = await apply_column_additions(conn)
            # Все колонки users, добавленные после первого релиза.
            assert applied == [
                "users.timezone", "users.daily_fiber_g", "users.referral",
                "users.legal_version", "users.legal_accepted_at", "users.marketing_consent",
            ]
            assert "timezone" in await conn.run_sync(_columns, "users")

            # Повторный запуск ничего не делает и не падает.
            assert await apply_column_additions(conn) == []
        await engine.dispose()

    asyncio.run(scenario())


def test_existing_column_is_left_alone():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE TABLE users (id INTEGER PRIMARY KEY, timezone VARCHAR(64))")
            )
            await conn.execute(text("INSERT INTO users VALUES (1, 'Asia/Yekaterinburg')"))

            # Существующую колонку не трогаем — добавляем только недостающие.
            assert "users.timezone" not in await apply_column_additions(conn)
            # Значение не затёрто значением по умолчанию.
            value = (await conn.execute(text("SELECT timezone FROM users"))).scalar_one()
            assert value == "Asia/Yekaterinburg"
        await engine.dispose()

    asyncio.run(scenario())


def test_no_table_means_no_migration():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            assert await apply_column_additions(conn) == []
        await engine.dispose()

    asyncio.run(scenario())
