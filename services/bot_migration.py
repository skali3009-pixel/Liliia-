"""Migration bridge. Never launches a broadcast automatically."""
import asyncio
from datetime import datetime, timezone
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, MenuButtonCommands
from sqlalchemy.exc import IntegrityError
import config
from db import get_session
from models.bot_migration import BotMigrationContact


def target_id():
    return int(config.BOT_TOKEN.split(":", 1)[0])


def target_url():
    return "https://t.me/" + config.BOT_USERNAME


def announcement():
    return (f"✨ AURA переезжает в новый бот — @{config.BOT_USERNAME}.\n\n"
            "Ваш профиль, записи и действующая подписка сохраняются. "
            "Откройте нового бота и нажмите «Начать» с того же Telegram-аккаунта. "
            "Дальше пользоваться AURA нужно там.\n\n"
            "История переписки останется в этом чате.")


def keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть AURA", url=target_url())]])


async def reachable(user_id):
    if not config.LEGACY_BOT_TOKEN:
        return True
    async with get_session() as session:
        contact = await session.get(BotMigrationContact, (target_id(), user_id))
        return bool(contact and contact.joined_at)


async def mark_joined(user_id):
    for attempt in range(2):
        try:
            async with get_session() as session:
                contact = await session.get(BotMigrationContact, (target_id(), user_id))
                if contact is None:
                    contact = BotMigrationContact(bot_id=target_id(), user_id=user_id)
                    session.add(contact)
                if not contact.joined_at:
                    contact.joined_at = datetime.now(timezone.utc)
                await session.commit()
            return
        except IntegrityError:
            if attempt:
                raise


class MigrationPresence(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if config.LEGACY_BOT_TOKEN and event.from_user:
            chat = getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None)
            if chat and chat.type == "private":
                await mark_joined(event.from_user.id)
        return await handler(event, data)


def legacy_dispatcher():
    """Keep replies to the previously delivered survey usable on the old bot."""
    from handlers import survey as survey_handler
    from services import survey

    dispatcher = Dispatcher()
    # Surveys sent before migration belong to the old Telegram identity.
    # Route only that campaign and its explicit comment replies, not product
    # handlers or arbitrary messages, before the generic redirect.
    dispatcher.callback_query.register(survey_handler.answer, F.data.startswith(survey.PREFIX))
    dispatcher.message.register(survey_handler.comment, survey_handler.SurveyReply())
    async def message(event):
        if event.chat.type == "private":
            await event.answer(announcement(), reply_markup=keyboard())
    async def callback(event):
        await event.answer("AURA переехала — открой нового бота", show_alert=True)
        if event.message and event.message.chat.type == "private":
            await event.message.answer(announcement(), reply_markup=keyboard())
    dispatcher.message.register(message)
    dispatcher.callback_query.register(callback)
    return dispatcher


async def legacy_bridge():
    """Old identity redirects and accepts replies to its existing survey."""
    old = Bot(config.LEGACY_BOT_TOKEN)
    dispatcher = legacy_dispatcher()
    try:
        await old.set_chat_menu_button(menu_button=MenuButtonCommands())
        await old.delete_my_commands()
        await old.set_my_description(description="AURA переехала: " + target_url() + ". Откройте нового бота и нажмите «Начать».")
        await dispatcher.start_polling(old, handle_signals=False)
    finally:
        await old.session.close()
