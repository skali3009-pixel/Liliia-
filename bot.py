"""Telegram-бот на aiogram, отвечающий с помощью Claude API."""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import config
from claude_client import ask_claude, reset_history

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Без принудительного Markdown-режима: ответы модели не всегда валидный
# Telegram-Markdown, а невалидная разметка приводит к ошибке отправки.
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    reset_history(message.chat.id)
    await message.answer(
        "Привет! Я AI-ассистент на базе Claude. Просто напишите мне сообщение — "
        "и я отвечу.\n\nКоманда /reset очищает историю диалога."
    )


@dp.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    reset_history(message.chat.id)
    await message.answer("История диалога очищена.")


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        reply = await ask_claude(message.chat.id, message.text)
    except Exception:
        logger.exception("Ошибка при обращении к Claude API")
        await message.answer(
            "Извините, произошла ошибка при обращении к AI. Попробуйте ещё раз чуть позже."
        )
        return

    # Telegram не принимает сообщения длиннее 4096 символов — режем на части.
    TELEGRAM_LIMIT = 4096
    for i in range(0, len(reply), TELEGRAM_LIMIT):
        await message.answer(reply[i : i + TELEGRAM_LIMIT])


async def main() -> None:
    logger.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
