"""Survey callbacks and explicit replies only; never takes over food/onboarding FSM."""
from datetime import datetime, timedelta, timezone
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter, Command
from aiogram.types import CallbackQuery, ForceReply, Message, BufferedInputFile
from db import async_session_maker
from models import SurveyResponse
from services import survey
from services.activity_audit import aware

router=Router(name='survey')
COMMENT_HEADER='Комментарий к опросу AURA.'


@router.message(Command('survey_results'))
async def results(message: Message):
    if message.chat.type!='private' or message.from_user.id not in survey.config.ADMIN_IDS: return
    data=await survey.snapshot()
    counts=data['delivery_counts']
    lines=['Опрос AURA',f"Доставлено: {counts.get('sent',0)}",f"Ответили: {data['responded']}",
           f"Бот заблокирован: {counts.get('blocked',0)}",
           f"Доставка требует проверки: {sum(counts.get(k,0) for k in ('unknown','sending','rate_limited','failed'))}"]
    lines += [f"{label}: {data['choice_counts'].get(code,0)}" for code,label in survey.CHOICES.items()]
    await message.answer('\n'.join(lines),parse_mode=None)
    comments=[f"{r['profile']} — {survey.CHOICES.get(r['choice'],'Без ответа')}\n{r['comment']}" for r in data['responses'] if r['comment']]
    if comments:
        await message.answer_document(BufferedInputFile('\n\n'.join(comments).encode('utf-8'),filename='aura-survey-comments.txt'),
                                      caption='Комментарии пользователей; текст приведён без интерпретации.')


def accepts_reply(row, message):
    return bool(row and row.choice and message.text and not message.text.startswith('/')
                and message.chat.type=='private' and message.reply_to_message
                and row.comment_prompt_id==message.reply_to_message.message_id
                and row.comment_until and aware(row.comment_until)>datetime.now(timezone.utc))


@router.callback_query(F.data.startswith(survey.PREFIX))
async def answer(callback: CallbackQuery):
    if not callback.message or callback.message.chat.type!='private' or callback.message.chat.id!=callback.from_user.id:
        await callback.answer('Опрос доступен в личном чате с ботом.'); return
    command=callback.data[len(survey.PREFIX):]
    async with async_session_maker() as session:
        row=await session.get(SurveyResponse,(survey.CAMPAIGN,callback.from_user.id))
        if row is None or (row.message_id and row.message_id!=callback.message.message_id):
            await callback.answer('Этот опрос недоступен.'); return
        if command.startswith('pick:') and command[5:] in survey.CHOICES:
            row.choice=command[5:]; row.answered_at=datetime.now(timezone.utc)
            row.comment_prompt_id=None; row.comment_until=None
            selected=row.choice
            await session.commit()
            await callback.answer('Ответ сохранён. Его можно изменить.')
            text=survey.TEXT+'\n\nВаш ответ: '+survey.CHOICES[selected]
            text+='\nСпасибо! Можно добавить комментарий или нажать «Готово».'
            if selected=='broken': text+=' Если захотите уточнить, расскажите, что именно не получилось.'
            try: await callback.message.edit_text(text,reply_markup=survey.keyboard(selected),parse_mode=None)
            except TelegramBadRequest as exc:
                if 'message is not modified' not in str(exc).lower(): raise
        elif command=='comment' and row.choice:
            await callback.answer()
            prompt=await callback.message.answer(
                COMMENT_HEADER+'\n\n'+('Что именно не получилось?' if row.choice=='broken' else 'Что нам стоит улучшить?')+
                '\nОтветьте на это сообщение в течение 30 минут. Комментарий необязателен.',
                reply_markup=ForceReply(input_field_placeholder='Необязательный комментарий, до 1500 знаков'))
            row.comment_prompt_id=prompt.message_id
            row.comment_until=datetime.now(timezone.utc)+timedelta(minutes=30)
            await session.commit()
        elif command=='done' and row.choice:
            row.comment_prompt_id=None; row.comment_until=None
            await session.commit()
            await callback.answer('Спасибо! Ответ сохранён.')
            try:
                await callback.message.edit_text(survey.TEXT+'\n\nСпасибо! Ваш ответ: '+survey.CHOICES[row.choice]+'\nПри желании выберите другой вариант.',
                                                 reply_markup=survey.keyboard(row.choice),parse_mode=None)
            except TelegramBadRequest as exc:
                if 'message is not modified' not in str(exc).lower(): raise
        else: await callback.answer('Сначала выберите ответ.')


class SurveyReply(Filter):
    async def __call__(self,message: Message):
        if not message.from_user or not message.reply_to_message or message.chat.type!='private': return False
        # Even an expired reply must not become a food-recognition request.
        reply=message.reply_to_message
        if (getattr(reply,'text','') or '').startswith(COMMENT_HEADER) and getattr(getattr(reply,'from_user',None),'id',None)==message.bot.id:
            return True
        async with async_session_maker() as session:
            row=await session.get(SurveyResponse,(survey.CAMPAIGN,message.from_user.id))
            return accepts_reply(row,message)


@router.message(SurveyReply())
async def comment(message: Message):
    text=(message.text or '').strip()
    if not text or len(text)>1500:
        await message.answer('Напишите от 1 до 1500 знаков ответом на вопрос о комментарии.'); return
    async with async_session_maker() as session:
        row=await session.get(SurveyResponse,(survey.CAMPAIGN,message.from_user.id))
        if not accepts_reply(row,message):
            await message.answer('Этот вопрос уже закрыт. Чтобы оставить комментарий, снова нажмите «Добавить комментарий» в опросе.')
            return
        row.comment=text; row.comment_prompt_id=None; row.comment_until=None
        row.answered_at=datetime.now(timezone.utc)
        await session.commit()
    await message.answer('Спасибо! Комментарий сохранён. Можно вернуться к AURA.')
