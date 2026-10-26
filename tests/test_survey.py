import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy import select
from aiogram.exceptions import TelegramForbiddenError,TelegramRetryAfter
from aiogram.methods import SendMessage
from models import Base,User,SurveyResponse
from services import survey
from handlers import survey as handler


@asynccontextmanager
async def database(monkeypatch):
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    maker=async_sessionmaker(engine,expire_on_commit=False)
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(survey,'async_session_maker',maker)
    monkeypatch.setattr(handler,'async_session_maker',maker)
    monkeypatch.setattr(survey.config,'ADMIN_IDS',{99})
    async with maker() as s:
        s.add_all([User(id=1,age=25),User(id=2,age=28),User(id=99,age=40),
                   User(id=3,age=16),User(id=4,reminders_enabled=False)])
        await s.commit()
    try: yield maker
    finally: await engine.dispose()


def test_preview_is_read_only_and_exclusions_are_explicit(monkeypatch):
    async def run():
        async with database(monkeypatch) as maker:
            result=await survey.snapshot()
            assert result['new_recipients']==2
            assert {r['reason'] for r in result['excluded']}=={'administrator','under_18','proactive_messages_disabled'}
            async with maker() as s: assert list(await s.scalars(select(SurveyResponse)))==[]
            assert all(len(b.callback_data.encode())<=64 for row in survey.keyboard().inline_keyboard for b in row)
    asyncio.run(run())


def test_delivery_is_durable_and_unknown_never_retried(monkeypatch):
    async def run():
        async with database(monkeypatch) as maker:
            bot=NS(send_message=AsyncMock(return_value=NS(message_id=100)))
            assert await survey.deliver_one(bot,1)=='sent'
            assert await survey.deliver_one(bot,1)=='skipped'
            assert await survey.deliver_one(bot,99)=='skipped'
            assert bot.send_message.await_count==1
            bot.send_message.side_effect=TimeoutError()
            assert await survey.deliver_one(bot,2)=='unknown'
            assert await survey.deliver_one(bot,2)=='skipped'
            assert bot.send_message.await_count==2
            result=await survey.snapshot()
            assert result['delivery_counts']=={'sent':1,'unknown':1}
            assert result['responded']==0
    asyncio.run(run())


def test_blocked_and_rate_limit_are_separate(monkeypatch):
    async def run():
        async with database(monkeypatch):
            method=SendMessage(chat_id=1,text='test')
            bot=NS(send_message=AsyncMock(side_effect=TelegramForbiddenError(method=method,message='blocked')))
            assert await survey.deliver_one(bot,1)=='blocked'
            bot.send_message.side_effect=TelegramRetryAfter(method=method,message='wait',retry_after=10)
            assert await survey.deliver_one(bot,2)=='rate_limited'
    asyncio.run(run())


def test_votes_can_change_and_comment_requires_explicit_matching_reply(monkeypatch):
    async def run():
        async with database(monkeypatch) as maker:
            await survey.deliver_one(NS(send_message=AsyncMock(return_value=NS(message_id=100))),1)
            message=NS(message_id=100,chat=NS(id=1,type='private'),edit_text=AsyncMock(),answer=AsyncMock(return_value=NS(message_id=101)))
            cb=NS(message=message,from_user=NS(id=1),data=survey.PREFIX+'pick:broken',answer=AsyncMock())
            await handler.answer(cb)
            cb.data=survey.PREFIX+'pick:forgot'; await handler.answer(cb)
            result=await survey.snapshot()
            assert result['responded']==1 and result['choice_counts']=={'forgot':1}
            cb.data=survey.PREFIX+'comment'; await handler.answer(cb)
            reply=NS(from_user=NS(id=1),chat=NS(id=1,type='private'),text='Не нашёл кнопку',reply_to_message=NS(message_id=101),answer=AsyncMock())
            assert await handler.SurveyReply()(reply)
            reply.reply_to_message.message_id=88
            assert not await handler.SurveyReply()(reply)
            reply.reply_to_message.message_id=101; reply.text='/start'
            assert not await handler.SurveyReply()(reply)
            reply.text='Не нашёл кнопку'
            await handler.comment(reply)
            assert not await handler.SurveyReply()(reply)
            assert (await survey.snapshot())['responses'][0]['comment']=='Не нашёл кнопку'
            cb.data=survey.PREFIX+'pick:using'; await handler.answer(cb)
            assert (await survey.snapshot())['choice_counts']=={'using':1}
            # Forwarded/copied survey and a different user's callback cannot vote.
            cb.from_user.id=2; cb.data=survey.PREFIX+'pick:broken'; await handler.answer(cb)
            assert (await survey.snapshot())['choice_counts']=={'using':1}
    asyncio.run(run())


def test_expired_or_unrequested_comment_does_not_capture_food():
    msg=NS(text='Съел рис',chat=NS(type='private'),reply_to_message=NS(message_id=4))
    row=NS(choice='broken',comment_prompt_id=None,comment_until=None)
    assert not handler.accepts_reply(row,msg)
    row.comment_prompt_id=4; row.comment_until=datetime.now(timezone.utc)-timedelta(seconds=1)
    assert not handler.accepts_reply(row,msg)


def test_campaign_stops_after_ambiguous_send(monkeypatch):
    async def run():
        async with database(monkeypatch):
            bot=NS(send_message=AsyncMock(side_effect=TimeoutError()))
            result=await survey.send_campaign(bot)
            assert bot.send_message.await_count==1
            assert result['delivery_counts']=={'unknown':1}
    asyncio.run(run())


def test_expired_survey_reply_is_consumed_and_not_sent_to_food(monkeypatch):
    async def run():
        async with database(monkeypatch):
            msg=NS(from_user=NS(id=1),chat=NS(type='private'),text='Не нашёл кнопку',
                   reply_to_message=NS(message_id=101,text=handler.COMMENT_HEADER,from_user=NS(id=700)),
                   bot=NS(id=700),answer=AsyncMock())
            assert await handler.SurveyReply()(msg)
            await handler.comment(msg)
            assert 'закрыт' in msg.answer.await_args.args[0]
            assert (await survey.snapshot())['responded']==0
    asyncio.run(run())


def test_results_are_only_for_owner_in_private_chat(monkeypatch):
    async def run():
        async with database(monkeypatch):
            msg=NS(from_user=NS(id=1),chat=NS(type='private'),answer=AsyncMock(),answer_document=AsyncMock())
            await handler.results(msg); msg.answer.assert_not_awaited()
            msg.from_user.id=99; msg.chat.type='group'
            await handler.results(msg); msg.answer.assert_not_awaited()
            msg.chat.type='private'
            await handler.results(msg)
            assert 'Ответили: 0' in msg.answer.await_args.args[0]
    asyncio.run(run())


def test_legacy_dispatcher_accepts_survey_vote_and_comment_but_redirects_other_messages(monkeypatch):
    """Real dispatcher routing for a survey sent by the previous bot identity."""
    from aiogram import Bot
    from aiogram.types import Update, CallbackQuery, Message, Chat, User as TgUser
    from aiogram.methods import SendMessage
    from services.bot_migration import legacy_dispatcher

    async def run():
        async with database(monkeypatch) as maker:
            await survey.deliver_one(NS(send_message=AsyncMock(return_value=NS(message_id=100))),1)
            calls=[]
            bot=Bot('123456:abcdefghijklmnopqrstuvwxyzABCDE')
            async def make_request(_bot, method, timeout=None):
                calls.append(method)
                if isinstance(method, SendMessage):
                    return Message(message_id=101, date=datetime.now(timezone.utc),
                                   chat=Chat(id=1,type='private'), text=method.text)
                return True
            monkeypatch.setattr(bot.session,'make_request',make_request)
            dispatcher=legacy_dispatcher()
            who=TgUser(id=1,is_bot=False,first_name='Test')
            chat=Chat(id=1,type='private')
            old_message=Message(message_id=100,date=datetime.now(timezone.utc),chat=chat,text=survey.TEXT)
            def callback(data, update_id):
                return Update(update_id=update_id, callback_query=CallbackQuery(
                    id=str(update_id),from_user=who,chat_instance='private',message=old_message,data=data))
            await dispatcher.feed_update(bot,callback('as16:pick:broken',1))
            await dispatcher.feed_update(bot,callback('as16:comment',2))
            prompt=Message(message_id=101,date=datetime.now(timezone.utc),chat=chat,
                           from_user=TgUser(id=bot.id,is_bot=True,first_name='Old'),text=handler.COMMENT_HEADER)
            reply=Message(message_id=102,date=datetime.now(timezone.utc),chat=chat,from_user=who,
                          text='Кнопка не работала',reply_to_message=prompt)
            await dispatcher.feed_update(bot,Update(update_id=3,message=reply))
            async with maker() as s:
                row=await s.get(SurveyResponse,(survey.CAMPAIGN,1))
                assert row.choice=='broken' and row.comment=='Кнопка не работала'
            normal=Message(message_id=103,date=datetime.now(timezone.utc),chat=chat,from_user=who,text='/start')
            await dispatcher.feed_update(bot,Update(update_id=4,message=normal))
            assert any(isinstance(call, SendMessage) and 'переезжает' in call.text for call in calls)
            await bot.session.close()
    asyncio.run(run())
