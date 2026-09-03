"""Точка входа: премиальный Telegram-бот для питания и тренировок (aiogram 3).

Роутеры подключены в порядке приоритета: онбординг (FSM) → главное меню →
legacy-ассистент (общий чат с Claude, Instagram-аудит) как запасной вариант
для любого текста, не пойманного предыдущими роутерами.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from db import init_models
from handlers import legacy, menu, onboarding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Без принудительного Markdown-режима: ответы модели не всегда валидный
# Telegram-Markdown, а невалидная разметка приводит к ошибке отправки.
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

dp.include_router(onboarding.router)
dp.include_router(menu.router)
dp.include_router(legacy.router)


async def main() -> None:
    logger.info("Инициализация базы данных...")
    await init_models()

    logger.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
