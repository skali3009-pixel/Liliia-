"""Точка входа: Telegram-бот для питания и тренировок (aiogram 3).

Роутеры подключены в порядке приоритета: онбординг (FSM) → добавление еды →
главное меню.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from db import init_models
from handlers import food, menu, onboarding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

dp.include_router(onboarding.router)
dp.include_router(food.router)
dp.include_router(menu.router)


async def main() -> None:
    logger.info("Инициализация базы данных...")
    await init_models()

    logger.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
