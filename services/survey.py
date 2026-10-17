"""Explicit campaign launch only. Never called by the scheduler or bot startup."""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import sys
from collections import Counter
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import config
from db import async_session_maker, engine
from models import User, SurveyResponse

CAMPAIGN = 'aura-feedback-20261016'
PREFIX = 'as16:'
TEXT = ('Что мешает пользоваться AURA чаще?\n\n'
        'Хотим сделать приложение удобнее. Выберите подходящий ответ — это займёт несколько секунд.\n\n'
        'Участие добровольное. Ответ и необязательный комментарий увидит команда AURA.')
CHOICES = {
    'unclear': 'Не разобрался, как пользоваться',
    'broken': 'Что-то не работало',
    'forgot': 'Забываю заходить',
    'no_value': 'Пока не вижу пользы для себя',
    'using': 'Пользуюсь, всё хорошо',
    'other': 'Другая причина',
}


def keyboard(selected=None):
    buttons = [[InlineKeyboardButton(text=('✓ ' if code == selected else '')+label,
                                     callback_data=PREFIX+'pick:'+code)] for code,label in CHOICES.items()]
    if selected:
        buttons += [[InlineKeyboardButton(text='Добавить комментарий', callback_data=PREFIX+'comment'),
                     InlineKeyboardButton(text='Готово', callback_data=PREFIX+'done')]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def alias(uid):
    return 'U-'+hmac.new(config.BOT_TOKEN.encode(),f'activity:{uid}'.encode(),hashlib.sha256).hexdigest()[:12]


def exclusion(user):
    if user.id in config.ADMIN_IDS: return 'administrator'
    if user.age is not None and user.age < 18: return 'under_18'
    if not user.reminders_enabled: return 'proactive_messages_disabled'
    return None


async def snapshot():
    async with async_session_maker() as session:
        users=(await session.execute(select(User.id,User.age,User.reminders_enabled).order_by(User.id))).all()
        saved=(await session.scalars(select(SurveyResponse).where(SurveyResponse.campaign==CAMPAIGN))).all()
        by_id={r.user_id:r for r in saved}
        candidates=[]; excluded=[]
        for u in users:
            why=exclusion(u)
            if why: excluded.append({'profile':alias(u.id),'reason':why})
            elif u.id not in by_id: candidates.append(alias(u.id))
        return {'campaign':CAMPAIGN,'text':TEXT,'choices':CHOICES,'new_recipients':len(candidates),
                'candidate_profiles':candidates,'excluded':excluded,
                'delivery_counts':dict(Counter(r.delivery for r in saved)),
                'responded':sum(bool(r.choice) for r in saved),
                'choice_counts':dict(Counter(r.choice for r in saved if r.choice)),
                'responses':[{'profile':alias(r.user_id),'delivery':r.delivery,'choice':r.choice,
                              'comment':r.comment,'answered_at':r.answered_at.isoformat() if r.answered_at else None,
                              'error_kind':r.error_kind} for r in saved],
                'note':'sending/unknown means uncertain delivery; never automatically retried. Existing rows are excluded from repeat sends.'}


async def reserve(uid):
    async with async_session_maker() as session:
        user=await session.get(User,uid)
        if user is None or exclusion(user): return False
        session.add(SurveyResponse(campaign=CAMPAIGN,user_id=uid,delivery='sending'))
        try: await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
        return True


async def deliver_one(bot, uid):
    if not await reserve(uid): return 'skipped'
    # Commit reservation before Telegram. A crash in this gap is deliberately
    # uncertain: manual reconciliation is preferable to a duplicate survey.
    status='unknown'; msg=None; error=None
    try:
        msg=await bot.send_message(uid,TEXT,reply_markup=keyboard(),parse_mode=None)
        status='sent'
    except TelegramRetryAfter:
        status='rate_limited'; error='TelegramRetryAfter'
    except TelegramForbiddenError:
        status='blocked'; error='TelegramForbiddenError'
    except TelegramBadRequest:
        status='failed'; error='TelegramBadRequest'
    except Exception as exc:
        error=type(exc).__name__
    async with async_session_maker() as session:
        row=await session.get(SurveyResponse,(CAMPAIGN,uid))
        if row is not None:
            row.delivery=status; row.error_kind=error
            if msg: row.message_id=msg.message_id; row.sent_at=datetime.now(timezone.utc)
            await session.commit()
    return status


async def send_campaign(bot):
    async with async_session_maker() as session:
        ids=list(await session.scalars(select(User.id).order_by(User.id)))
    for uid in ids:
        status=await deliver_one(bot,uid)
        if status in {'unknown','rate_limited'}: break
        if status!='skipped': await asyncio.sleep(0.25)
    return await snapshot()


async def main():
    try:
        if sys.argv[1:] == ['send','CONFIRM_AURA_FEEDBACK_20261016']:
            async with Bot(config.BOT_TOKEN) as bot: result=await send_campaign(bot)
        elif sys.argv[1:] in (['preview'],['report']): result=await snapshot()
        else: raise SystemExit('Use preview or report. Sending requires the exact campaign confirmation.')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally: await engine.dispose()


if __name__=='__main__': asyncio.run(main())
