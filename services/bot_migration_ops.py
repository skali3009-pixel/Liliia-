"""Explicit, scoped operator migration. Secrets only via stdin and protected .env."""
import asyncio
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest
from dotenv import dotenv_values
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

import config
from db import get_session, engine
from models import User, Subscription, Meal, WaterLog, WorkoutLog, BodyMeasurement, Payment, ProgressPhoto
from models.bot_migration import BotMigrationContact
from services import bot_migration as migration

SOURCE_ID = 8772631894
TARGET_ID = 8803066420
TARGET_NAME = "aura_scalia_bot"
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "bot-migration-20261022"


async def snapshot():
    async with get_session() as session:
        counts = {m.__tablename__: await session.scalar(select(func.count()).select_from(m))
                  for m in (User, Subscription, Meal, WaterLog, WorkoutLog, BodyMeasurement, Payment, ProgressPhoto)}
        subs = (await session.execute(select(Subscription).order_by(Subscription.user_id))).scalars().all()
        values = [[s.user_id, str(s.expires_at), s.lifetime, str(s.status), str(s.source)] for s in subs]
        counts['subscription_digest'] = hashlib.sha256(json.dumps(values).encode()).hexdigest()
        counts['legacy_progress_file_ids'] = await session.scalar(select(func.count()).select_from(ProgressPhoto).where(ProgressPhoto.photo_file_id.is_not(None)))
        return counts


async def configure():
    new = sys.stdin.readline().strip()
    if not re.fullmatch(r"\d{6,15}:[A-Za-z0-9_-]{30,}", new):
        raise ValueError("Invalid token format")
    async with Bot(new) as target:
        who = await target.get_me()
        webhook = await target.get_webhook_info()
        if who.id != TARGET_ID or who.username != TARGET_NAME or webhook.url:
            raise ValueError("Unexpected target identity or existing webhook")
    if migration.target_id() != SOURCE_ID or config.LEGACY_BOT_TOKEN:
        raise ValueError("Source identity changed; refusing repeated configure")
    async with Bot(config.BOT_TOKEN) as old:
        if (await old.get_me()).id != SOURCE_ID:
            raise ValueError('Source mismatch')
        original_description = (await old.get_my_description()).description
    before = await snapshot()
    if before['legacy_progress_file_ids']:
        raise ValueError("Old Telegram photo references need migration first")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    env_path = ROOT / '.env'
    backup = STATE / 'original.env'
    if backup.exists():
        raise ValueError("Backup already exists; inspect previous attempt")
    with backup.open('x', encoding='utf-8') as f:
        os.chmod(backup, 0o600)
        f.write(env_path.read_text(encoding='utf-8'))
    (STATE/'before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    (STATE/'original-description.json').write_text(json.dumps(original_description), encoding='utf-8')
    values = {'BOT_TOKEN': new, 'LEGACY_BOT_TOKEN': config.BOT_TOKEN, 'BOT_USERNAME': TARGET_NAME}
    lines = [line for line in env_path.read_text(encoding='utf-8').splitlines()
             if not re.match(r'^\s*(?:export\s+)?(?:BOT_TOKEN|LEGACY_BOT_TOKEN|BOT_USERNAME)\s*=', line)]
    lines += [key+'='+value for key, value in values.items()]
    temporary = env_path.with_name('.env.migration-tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines)+'\n'); f.flush(); os.fsync(f.fileno())
    os.replace(temporary, env_path)
    print(json.dumps({'configured': True, 'target': TARGET_NAME, 'before': before}))


async def rollback():
    if migration.target_id() != TARGET_ID or not config.LEGACY_BOT_TOKEN:
        raise ValueError('Not a configured migration')
    original = (STATE/'original.env').read_text(encoding='utf-8')
    from io import StringIO
    source_token = dotenv_values(stream=StringIO(original)).get('BOT_TOKEN', '')
    if source_token != config.LEGACY_BOT_TOKEN:
        raise ValueError('Backup identity mismatch')
    async with Bot(source_token) as old:
        await old.set_my_description(description=json.loads((STATE/'original-description.json').read_text()))
    temporary = ROOT/'.env.rollback-tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(original); f.flush(); os.fsync(f.fileno())
    os.replace(temporary, ROOT/'.env')
    print(json.dumps({'restored_configuration': True, 'restart_required': True}))


async def inspect():
    current = await snapshot()
    before_path = STATE/'before.json'
    before = json.loads(before_path.read_text()) if before_path.exists() else None
    async with Bot(config.BOT_TOKEN) as bot:
        who = await bot.get_me()
        menu = await bot.get_chat_menu_button()
        webhook = await bot.get_webhook_info()
    async with get_session() as session:
        rows = (await session.scalars(select(BotMigrationContact).where(BotMigrationContact.bot_id == TARGET_ID))).all()
    print(json.dumps({'bot_id': who.id, 'username': who.username, 'menu': menu.model_dump(exclude_none=True),
                     'webhook_set': bool(webhook.url), 'snapshot': current,
                     'before_matches': current == before if before else None,
                     'joined': sum(bool(r.joined_at) for r in rows),
                     'delivery': dict(Counter(r.delivery or 'not_sent' for r in rows))}, ensure_ascii=False))


async def broadcast():
    if migration.target_id() != TARGET_ID or not config.LEGACY_BOT_TOKEN:
        raise ValueError('Migration not configured')
    async with Bot(config.LEGACY_BOT_TOKEN) as old, Bot(config.BOT_TOKEN) as new:
        if (await old.get_me()).id != SOURCE_ID or (await new.get_me()).username != TARGET_NAME:
            raise ValueError('Identity mismatch')
        async with get_session() as session:
            users = list(await session.scalars(select(User.id).order_by(User.id)))
        for uid in users:
            # Claim before send; unknown Telegram outcomes are never retried.
            try:
                async with get_session() as session:
                    contact = await session.get(BotMigrationContact, (TARGET_ID, uid), with_for_update=True)
                    if contact and contact.delivery:
                        continue
                    if contact is None:
                        contact = BotMigrationContact(bot_id=TARGET_ID, user_id=uid)
                        session.add(contact)
                    contact.delivery = 'sending'
                    await session.commit()
            except IntegrityError:
                continue
            status, message_id, error = 'unknown', None, None
            try:
                msg = await old.send_message(uid, migration.announcement(), reply_markup=migration.keyboard())
                status, message_id = 'sent', msg.message_id
            except TelegramRetryAfter as exc:
                status, error = 'rate_limited', type(exc).__name__
            except TelegramForbiddenError as exc:
                status, error = 'blocked', type(exc).__name__
            except TelegramBadRequest as exc:
                status, error = 'unavailable', type(exc).__name__
            except Exception as exc:
                error = type(exc).__name__
            async with get_session() as session:
                contact = await session.get(BotMigrationContact, (TARGET_ID, uid), with_for_update=True)
                contact.delivery, contact.message_id, contact.error_kind = status, message_id, error
                await session.commit()
            await asyncio.sleep(0.15)
    await inspect()


async def main():
    try:
        action = sys.argv[1] if len(sys.argv)>1 else 'inspect'
        if action == 'configure': await configure()
        elif action == 'inspect': await inspect()
        elif action == 'broadcast': await broadcast()
        elif action == 'rollback': await rollback()
        else: raise ValueError('Unknown action')
    except Exception as exc:
        # Neither traceback nor HTTP exception strings may expose tokens.
        print(json.dumps({'error': type(exc).__name__})); raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
