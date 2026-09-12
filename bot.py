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
from services.fsm_storage import DatabaseStorage
from services import commands as bot_commands
from services import identity
from handlers import (access, diary, errors, fallback, feedback, food, legal,
                      notifications, onboarding, profile, progress, steps,
                      suggestions, supplements, turn, water, workouts)
from middlewares.access import AccessMiddleware
from middlewares.presence import PresenceMiddleware
from scheduler import start_scheduler
from webapp.server import start_webapp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
# Состояние разговоров хранится в базе, а не в памяти: бот обновляется
# сам раз в полчаса, и с памятью каждый такой перезапуск стирал
# незаконченные карточки еды и недописанные анкеты.
dp = Dispatcher(storage=DatabaseStorage())

# Проверка доступа стоит до всех обработчиков: без подписки бот отвечает
# только про оплату.
dp.message.outer_middleware(AccessMiddleware())
dp.callback_query.outer_middleware(AccessMiddleware())

# Отметка «человек сейчас здесь»: по ней движок уведомлений не пишет
# первым тому, кто и так разговаривает с ботом.
dp.message.outer_middleware(PresenceMiddleware())
dp.callback_query.outer_middleware(PresenceMiddleware())

dp.include_router(legal.router)
dp.include_router(access.router)
dp.include_router(onboarding.router)
# Профиль раньше еды: он снимает состояние правки, когда человек уходит из
# незаконченного ответа в другую кнопку меню.
dp.include_router(profile.router)
# «Что-то не так» — тоже раньше кнопок меню: пока человек пишет, его текст
# не должен уезжать ни в еду, ни в профиль.
dp.include_router(feedback.router)
# «Мой ход» тоже раньше еды: нажатый посреди добавления блюда, он иначе
# уедет в распознавание как название.
dp.include_router(turn.router)
# Кнопки под подсказками бота: вода в одно нажатие, «позже», «не сегодня».
dp.include_router(notifications.router)
# Шаги тоже раньше еды: число «8500», присланное в ответ, иначе уедет в
# распознавание как название блюда.
dp.include_router(steps.router)
dp.include_router(diary.router)
dp.include_router(food.router)
dp.include_router(water.router)
dp.include_router(supplements.router)
dp.include_router(progress.router)
dp.include_router(workouts.router)
dp.include_router(suggestions.router)
# Последним: сюда попадает только то, что не разобрал никто выше.
# До него бот на непонятое просто молчал, и человек не знал, дошло
# ли сообщение вообще.
dp.include_router(fallback.router)

# Падение любого обработчика: человеку — честный ответ, владельцу — место
# поломки. Без этого ошибка уходила только в лог, куда никто не смотрит.
dp.errors.register(errors.on_error)


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
    elif not config.ADMIN_IDS:
        logger.warning(
            "Бот бесплатен для всех, и ADMIN_IDS не задан: отчёты о расходах "
            "и предупреждения о сбоях отправлять некому. Узнать свой номер — "
            "команда /id боту, вписать — bash set-admin.sh <номер>"
        )
    else:
        logger.info(
            "Бот бесплатен для всех (PAYWALL=0). Включить оплату — "
            "bash set-paywall.sh on. Состояние целиком — bash status.sh"
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

    runner = await start_webapp(bot)
    scheduler = start_scheduler(bot)
    try:
        # До кнопок: от имени бота зависят ссылки-приглашения.
        await identity.learn_username(bot)
        await setup_menu_button()
        # Список команд в меню Telegram: без него о /problem, /steps
        # и /delete знает только тот, кому их назвали вслух.
        await bot_commands.apply(bot)
        logger.info("Бот запускается...")
        await dp.start_polling(bot)
    finally:
        artwork_task.cancel()
        scheduler.shutdown(wait=False)
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
