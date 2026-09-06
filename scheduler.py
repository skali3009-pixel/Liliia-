"""Планировщик: раз в минуту проверяет, кому пора принять препарат."""

from __future__ import annotations

import logging
from datetime import date

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from db import get_session
from keyboards.supplements import reminder_keyboard
from services.meal_reminders import users_without_meals_today
from services.reminders import collect_due_reminders
from services.selfupdate import run_update
from services.subscriptions import expire_overdue, expiring_soon, mark_warned
from services.water_reminders import render as render_water
from services.water_reminders import users_behind_on_water
from services.weekly import build_summary, render, users_for_summary

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


async def send_meal_nudges(bot: Bot) -> None:
    """Вечером — тем, кто ничего не занёс за день."""
    try:
        async with get_session() as session:
            nudges = await users_without_meals_today(session)
    except Exception:
        logger.exception("Не удалось собрать напоминания о дневнике")
        return

    for nudge in nudges:
        key = (nudge.user_id, "meal_nudge")
        if key in _already_sent:
            continue
        try:
            await bot.send_message(
                nudge.user_id,
                "🍽 Сегодня ещё нет ни одной записи о еде.\n\n"
                "Не страшно, если день был не по плану — просто занеси, что "
                "успела съесть, дневник от этого не сломается.",
            )
            _already_sent.add(key)
        except Exception:
            logger.info("Не получилось напомнить про дневник %s", nudge.user_id)


async def send_water_nudges(bot: Bot) -> None:
    """Днём — тем, кто к середине дня выпил меньше половины нормы."""
    try:
        async with get_session() as session:
            nudges = await users_behind_on_water(session)
    except Exception:
        logger.exception("Не удалось собрать напоминания о воде")
        return

    for nudge in nudges:
        key = (nudge.user_id, "water_nudge")
        if key in _already_sent:
            continue
        try:
            await bot.send_message(nudge.user_id, render_water(nudge))
            _already_sent.add(key)
        except Exception:
            logger.info("Не получилось напомнить про воду %s", nudge.user_id)


async def send_weekly_summaries(bot: Bot) -> None:
    """Воскресным вечером — неделя целиком, одним сообщением."""
    try:
        async with get_session() as session:
            users = await users_for_summary(session)
            summaries = [
                (user, await build_summary(session, user),
                 user.goal.value if user.goal else None)
                for user in users
            ]
    except Exception:
        logger.exception("Не удалось собрать итоги недели")
        return

    for user, summary, goal in summaries:
        key = (user.id, "weekly")
        if key in _already_sent:
            continue
        # Неделя, в которой не было вообще ничего, — не повод для рассылки.
        if summary.is_empty:
            _already_sent.add(key)
            continue
        try:
            await bot.send_message(user.id, render(summary, goal=goal))
            _already_sent.add(key)
        except Exception:
            logger.info("Не получилось отправить итоги недели %s", user.id)


async def check_subscriptions(bot: Bot) -> None:
    """Предупредить, у кого подписка на исходе, и закрыть истёкшие."""
    try:
        async with get_session() as session:
            soon = await expiring_soon(session, days=3)
            for subscription in soon:
                left = max((subscription.expires_at.date() - date.today()).days, 0)
                try:
                    await bot.send_message(
                        subscription.user_id,
                        f"⏳ Доступ заканчивается через {left} дн.\n\n"
                        "Записи останутся на месте, но дневник, распознавание еды и "
                        "тренировки закроются. Продлить — /subscription",
                    )
                    await mark_warned(session, subscription)
                except Exception:
                    logger.info("Не получилось предупредить %s", subscription.user_id)

            ended = await expire_overdue(session)

        for user_id in ended:
            try:
                await bot.send_message(
                    user_id,
                    "🔒 Доступ закончился.\n\n"
                    "Всё записанное сохранено и ждёт тебя — вернуть доступ можно "
                    "командой /subscription.",
                )
            except Exception:
                logger.info("Не получилось сообщить %s об окончании доступа", user_id)
    except Exception:
        logger.exception("Проверка подписок не удалась")



async def report_costs(bot: Bot) -> None:
    """Утренний отчёт владельцу: сколько вчера потратили и как с диском.

    Расход на модель — единственная статья, которая может вырасти внезапно.
    Владелец должен видеть её каждый день, а не в конце месяца в счёте.
    """
    if not config.ADMIN_IDS:
        return

    from datetime import date, timedelta

    from services import usage as usage_service
    from utils.disk import render_warning
    from utils.disk import usage as disk_usage

    async with get_session() as session:
        yesterday = await usage_service.spent_today(session, date.today() - timedelta(days=1))
        await usage_service.cleanup(session)

    lines = [usage_service.render_report(yesterday)]
    if yesterday.total_usd >= config.DAILY_COST_LIMIT_USD:
        lines.append("\n⚠️ Дневной потолок вчера был исчерпан — распознавание фото "
                     "приостанавливалось.")

    disk = disk_usage()
    if disk.warning:
        lines.append("\n" + render_warning(disk))

    text = "\n".join(lines)
    for admin in config.ADMIN_IDS:
        try:
            await bot.send_message(admin, text)
        except Exception:  # noqa: BLE001 — владелец мог заблокировать бота
            logger.warning("Не удалось отправить отчёт о расходах владельцу %s", admin)


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_due_reminders, "cron", minute="*", args=[bot], id="supplements")
    scheduler.add_job(send_meal_nudges, "cron", minute="*", args=[bot], id="meal_nudges")
    scheduler.add_job(send_water_nudges, "cron", minute="*", args=[bot], id="water_nudges")
    scheduler.add_job(send_weekly_summaries, "cron", minute="*", args=[bot], id="weekly")
    scheduler.add_job(clear_sent_marks, "cron", hour=0, minute=1, id="cleanup")
    # Раз в день утром: предупредить об окончании и закрыть просроченные.
    scheduler.add_job(check_subscriptions, "cron", hour=6, minute=0, args=[bot],
                      id="subscriptions")
    # Отчёт о расходах — раньше, чем начинается день: чтобы владелец успел
    # среагировать до наплыва.
    scheduler.add_job(report_costs, "cron", hour=5, minute=30, args=[bot], id="costs")

    if config.AUTO_UPDATE:
        # Раз в полчаса — не чаще: обновление перезапускает бота, и делать
        # это посреди разговора незачем.
        scheduler.add_job(run_update, "interval", minutes=30, id="selfupdate")
        logger.info("Автообновление включено (раз в 30 минут)")

    scheduler.start()
    logger.info("Планировщик напоминаний запущен")
    return scheduler
