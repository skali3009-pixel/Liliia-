"""Планировщик: раз в минуту проверяет, кому пора принять препарат."""

from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from db import get_session
from keyboards.supplements import reminder_keyboard
from services.reminders import collect_due_reminders
from services.selfupdate import run_update

logger = logging.getLogger(__name__)

# Чтобы перезапуск планировщика внутри той же минуты не прислал повтор.
_already_sent: set[tuple[int, str]] = set()


async def send_due_reminders(bot: Bot) -> None:
    try:
        async with get_session() as session:
            reminders = await collect_due_reminders(session)
    except Exception:
        logger.exception("Не удалось собрать напоминания")
        return

    for reminder in reminders:
        key = (reminder.supplement_id, str(reminder.user_id))
        if key in _already_sent:
            continue

        dose = f" ({reminder.dose})" if reminder.dose else ""
        try:
            await bot.send_message(
                reminder.user_id,
                f"💊 Пора принять: {reminder.name}{dose}",
                reply_markup=reminder_keyboard(reminder.supplement_id),
            )
            _already_sent.add(key)
        except Exception:
            logger.exception("Не удалось отправить напоминание пользователю %s", reminder.user_id)


def clear_sent_marks() -> None:
    """Сбрасываем отметки об отправке — вызывается раз в сутки."""
    _already_sent.clear()


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_due_reminders, "cron", minute="*", args=[bot], id="supplements")
    scheduler.add_job(clear_sent_marks, "cron", hour=0, minute=1, id="cleanup")

    if config.AUTO_UPDATE:
        # Раз в полчаса — не чаще: обновление перезапускает бота, и делать
        # это посреди разговора незачем.
        scheduler.add_job(run_update, "interval", minutes=30, id="selfupdate")
        logger.info("Автообновление включено (раз в 30 минут)")

    scheduler.start()
    logger.info("Планировщик напоминаний запущен")
    return scheduler
