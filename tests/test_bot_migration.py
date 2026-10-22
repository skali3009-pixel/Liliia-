import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import config
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from models.base import Base
from models.bot_migration import BotMigrationContact
from services import bot_migration as migration
import pytest


def test_join_is_durable_and_does_not_change_delivery(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as conn:
            await conn.run_sync(BotMigrationContact.__table__.create)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        @asynccontextmanager
        async def session():
            async with factory() as s: yield s
        monkeypatch.setattr(migration, 'get_session', session)
        monkeypatch.setattr(config, 'LEGACY_BOT_TOKEN', 'old')
        monkeypatch.setattr(config, 'BOT_TOKEN', '8803066420:test')
        assert not await migration.reachable(42)
        async with factory() as s:
            s.add(BotMigrationContact(bot_id=8803066420, user_id=42, delivery='sent', message_id=123))
            await s.commit()
        await migration.mark_joined(42)
        await migration.mark_joined(42)
        assert await migration.reachable(42)
        async with factory() as s:
            row = await s.get(BotMigrationContact, (8803066420, 42))
            assert row.delivery == 'sent' and row.message_id == 123
        monkeypatch.setattr(config, 'BOT_TOKEN', '111111:test')
        assert not await migration.reachable(42)
        await engine.dispose()
    asyncio.run(run())


def test_unmigrated_install_keeps_delivery(monkeypatch):
    monkeypatch.setattr(config, 'LEGACY_BOT_TOKEN', '')
    assert asyncio.run(migration.reachable(42))


def test_presence_does_not_enable_private_delivery_from_group(monkeypatch):
    monkeypatch.setattr(config, 'LEGACY_BOT_TOKEN', 'old')
    mark = AsyncMock(); monkeypatch.setattr(migration, 'mark_joined', mark)
    handler = AsyncMock()
    event = SimpleNamespace(from_user=SimpleNamespace(id=42), chat=SimpleNamespace(type='group'))
    asyncio.run(migration.MigrationPresence()(handler, event, {}))
    mark.assert_not_awaited(); handler.assert_awaited_once()


def test_announcement_targets_current_username(monkeypatch):
    monkeypatch.setattr(config, 'BOT_USERNAME', 'aura_scalia_bot')
    assert '@aura_scalia_bot' in migration.announcement()
    assert migration.keyboard().inline_keyboard[0][0].url == 'https://t.me/aura_scalia_bot'


@pytest.mark.parametrize('uncertain', [False, True])
def test_broadcast_does_not_resend_sent_or_ambiguous_delivery(monkeypatch, uncertain):
    from tests.test_platega import database
    from services import platega, bot_migration_ops as ops
    calls = []
    class FakeBot:
        def __init__(self, token): self.token = token
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get_me(self):
            return SimpleNamespace(id=int(self.token.split(':')[0]), username='aura_scalia_bot')
        async def send_message(self, uid, text, **kwargs):
            calls.append(uid)
            if uncertain: raise TimeoutError()
            return SimpleNamespace(message_id=123)
    monkeypatch.setattr(config, 'BOT_TOKEN', '8803066420:test')
    monkeypatch.setattr(config, 'LEGACY_BOT_TOKEN', '8772631894:test')
    monkeypatch.setattr(ops, 'Bot', FakeBot)
    monkeypatch.setattr(ops, 'inspect', AsyncMock())
    async def run():
        async with database(monkeypatch) as factory:
            monkeypatch.setattr(ops, 'get_session', platega.get_session)
            await ops.broadcast()
            await ops.broadcast()
            assert calls == [501]
            async with factory() as s:
                row = await s.get(BotMigrationContact, (8803066420, 501))
                assert row.delivery == ('unknown' if uncertain else 'sent')
    asyncio.run(run())


def test_scheduler_waits_until_user_joins_even_without_paywall(monkeypatch):
    import scheduler
    monkeypatch.setattr(config, 'PAYWALL', False)
    monkeypatch.setattr(migration, 'reachable', AsyncMock(return_value=False))
    assert not asyncio.run(scheduler.product_messages_allowed(42))


def test_checkout_redirect_uses_new_bot(monkeypatch):
    from tests.test_platega import database
    from services import platega
    from uuid import uuid4
    monkeypatch.setattr(config, 'BOT_USERNAME', 'aura_scalia_bot')
    monkeypatch.setattr(platega, 'enabled', lambda *args: True)
    request = AsyncMock(return_value={'transactionId': str(uuid4()), 'url': 'https://pay.platega.io/p/test'})
    monkeypatch.setattr(platega, 'api', request)
    async def run():
        async with database(monkeypatch):
            await platega.create_order(501)
            payload = request.call_args.args[2]
            assert payload['return'] == payload['failedUrl'] == 'https://t.me/aura_scalia_bot'
    asyncio.run(run())
