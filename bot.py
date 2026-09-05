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
from services.artwork import ensure_artwork
from handlers import (access, food, legal, menu, onboarding, progress,
                      suggestions, supplements, water, workouts)
from middlewares.access import AccessMiddleware
from scheduler import start_scheduler
from webapp.server import start_webapp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# Проверка доступа стоит до всех обработчиков: без подписки бот отвечает
# только про оплату.
dp.message.outer_middleware(AccessMiddleware())
dp.callback_query.outer_middleware(AccessMiddleware())

dp.include_router(legal.router)
dp.include_router(access.router)
dp.include_router(onboarding.router)
dp.include_router(food.router)
dp.include_router(water.router)
dp.include_router(supplements.router)
dp.include_router(progress.router)
dp.include_router(workouts.router)
dp.include_router(suggestions.router)
dp.include_router(menu.router)


async def setup_menu_button() -> None:
    """Кнопка «Открыть приложение» рядом с полем ввода в чате."""
    if not config.WEBAPP_URL:
        return
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text=config.WEBAPP_BUTTON, web_app=WebAppInfo(url=config.WEBAPP_URL)
        )
    )
    logger.info("Кнопка мини-приложения включена: %s", config.WEBAPP_URL)


def warn_about_setup() -> None:
    """Сказать вслух то, что владелец иначе заметит только от юриста."""
    # Первой строкой в журнале — главный вопрос: бот открыт или закрыт.
    if config.PAYWALL:
        logger.info(
            "Доступ платный: пробный период %d дн., далее %d ⭐ в месяц",
            config.TRIAL_DAYS, config.SUB_PRICE_STARS,
        )
    else:
        logger.info(
            "Доступ открыт всем: ADMIN_IDS не задан либо PAYWALL=0. "
            "Проверить состояние целиком — bash status.sh"
        )

    if config.PAYWALL and not config.LEGAL_OWNER:
        logger.warning(
            "Платный доступ включён, но LEGAL_OWNER пуст: оферта выйдет без "
            "реквизитов. Заполни LEGAL_OWNER, LEGAL_REQUISITES и LEGAL_EMAIL в .env."
        )
    if config.LEGAL_OWNER and not config.WEBAPP_URL:
        logger.warning(
            "Документы некуда публиковать: не задан WEBAPP_URL, ссылки в боте "
            "показаны не будут."
        )


async def main() -> None:
    warn_about_setup()
    logger.info("Инициализация базы данных...")
    await init_models()

    # Картинки качаются фоном: без них приложение работает, а ждать их
    # на старте незачем. Ссылку держим, чтобы задачу не собрал сборщик.
    artwork_task = asyncio.create_task(ensure_artwork())

    runner = await start_webapp()
    scheduler = start_scheduler(bot)
    try:
        await setup_menu_button()
        logger.info("Бот запускается...")
        await dp.start_polling(bot)
    finally:
        artwork_task.cancel()
        scheduler.shutdown(wait=False)
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
