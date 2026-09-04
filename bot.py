"""Точка входа: Telegram-бот для питания и тренировок (aiogram 3).

Роутеры подключены в порядке приоритета: онбординг (FSM) → добавление еды →
главное меню.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo

import config
from db import init_models
from handlers import food, menu, onboarding, progress, supplements, water, workouts
from scheduler import start_scheduler
from webapp.server import start_webapp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

dp.include_router(onboarding.router)
dp.include_router(food.router)
dp.include_router(water.router)
dp.include_router(supplements.router)
dp.include_router(progress.router)
dp.include_router(workouts.router)
dp.include_router(menu.router)


async def setup_menu_button() -> None:
    """Кнопка «Открыть приложение» рядом с полем ввода в чате."""
    if not config.WEBAPP_URL:
        return
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Дневник", web_app=WebAppInfo(url=config.WEBAPP_URL)
        )
    )
    logger.info("Кнопка мини-приложения включена: %s", config.WEBAPP_URL)


async def main() -> None:
    logger.info("Инициализация базы данных...")
    await init_models()

    runner = await start_webapp()
    scheduler = start_scheduler(bot)
    try:
        await setup_menu_button()
        logger.info("Бот запускается...")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
