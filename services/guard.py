"""Сторож внутри бота: следит за диском, бюджетом и резкими скачками.

Отличается от watchdog.sh: тот проверяет снаружи, жив ли процесс, а этот
смотрит изнутри на то, что может испортиться при живом боте — кончается
место, исчерпан дневной потолок, расход внезапно пошёл вверх.

Все сообщения идут через services.alerts, поэтому повторов не будет:
сигнал уходит один раз и молчит, пока состояние не изменится.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

import config
from db import get_session
from services import alerts
from services import usage as usage_service
from utils.disk import render_warning
from utils.disk import usage as disk_usage

logger = logging.getLogger(__name__)

# Доля дневного потолка, потраченная за час, после которой стоит насторожиться.
SPIKE_SHARE = 0.5


async def check_disk(bot: Bot) -> None:
    """Место на диске: предупредить заранее, а не когда всё встало."""
    disk = disk_usage()
    if disk.full:
        await alerts.fire(bot, alerts.DISK, "full", render_warning(disk) + _disk_hint())
    elif disk.warning:
        await alerts.fire(bot, alerts.DISK, "warn", render_warning(disk) + _disk_hint())
    else:
        await alerts.resolve(
            bot, alerts.DISK,
            f"✅ С диском снова нормально: занято {disk.percent}%, "
            f"свободно {disk.free_gb} ГБ.",
        )


def _disk_hint() -> str:
    """Сигнал без готовой команды заставляет искать, что делать."""
    return ("\n\nПосмотреть, что занимает место:\n"
            "`du -sh /root/nutrition-bot/data/* | sort -h`")


async def check_budget(bot: Bot) -> None:
    """Дневной потолок расходов: люди узнают об этом раньше владельца."""
    if config.DAILY_COST_LIMIT_USD <= 0:
        return

    async with get_session() as session:
        spend = await usage_service.spent_today(session)

    if spend.total_usd >= config.DAILY_COST_LIMIT_USD:
        await alerts.fire(
            bot, alerts.BUDGET, "over",
            f"🛑 Дневной потолок исчерпан: {spend.total_usd:.2f} $ из "
            f"{config.DAILY_COST_LIMIT_USD:.0f} $.\n\n"
            "Распознавание фото и голоса до полуночи отключено — дневник, "
            "тренировки и всё остальное работают.\n\n"
            "Поднять потолок: `bash set-limit.sh <сумма>`",
        )
    else:
        await alerts.resolve(
            bot, alerts.BUDGET,
            f"✅ Новый день, потолок сброшен. Потрачено {spend.total_usd:.2f} $ "
            f"из {config.DAILY_COST_LIMIT_USD:.0f} $.",
        )


async def check_spike(bot: Bot) -> None:
    """Расход пошёл вверх быстрее обычного — наплыв или злоупотребление."""
    if config.DAILY_COST_LIMIT_USD <= 0:
        return

    edge = config.DAILY_COST_LIMIT_USD * SPIKE_SHARE
    async with get_session() as session:
        hour = await usage_service.spent_since(session, _hour_ago())

    if hour >= edge:
        # Ключ включает округлённую сумму: следующий, ещё больший скачок
        # пройдёт как новое событие, а не как повтор старого.
        await alerts.fire(
            bot, alerts.SPIKE, f"{hour:.0f}",
            f"📈 За последний час потрачено {hour:.2f} $ — это больше половины "
            f"дневного потолка ({config.DAILY_COST_LIMIT_USD:.0f} $).\n\n"
            "Похоже на наплыв людей или на то, что кто-то шлёт фото пачками. "
            "Посмотреть: `bash status.sh`",
        )
    elif hour < edge / 2:
        await alerts.resolve(bot, alerts.SPIKE, "✅ Расход вернулся к обычному.")


def _hour_ago() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=1)


async def watch(bot: Bot) -> None:
    """Один проход всех проверок. Ошибка в одной не должна ронять остальные."""
    for name, check in (("диск", check_disk), ("бюджет", check_budget),
                        ("скачок расхода", check_spike)):
        try:
            await check(bot)
        except Exception:
            logger.exception("Проверка «%s» не удалась", name)


__all__ = ["SPIKE_SHARE", "check_budget", "check_disk", "check_spike", "watch"]
