"""Планировщик: раз в минуту проверяет, кому пора принять препарат."""

from __future__ import annotations

import logging
from datetime import date, time

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from db import get_session
from keyboards.notifications import comeback_keyboard, nudge_keyboard
from keyboards.supplements import reminder_keyboard
from services.reminders import collect_due_reminders
from services import fsm_storage
from services import notifications
from services import comeback, guard, metrics
from services.gamification import remember_suggestion
from services import step_results
from services import owner_reports as owner_reports_text
from services import usage
from services.selfupdate import run_update
from services.subscriptions import expire_overdue, expiring_soon, mark_warned
from services.weekly import build_summary, render, users_for_summary

logger = logging.getLogger(__name__)

# Чтобы перезапуск планировщика внутри той же минуты не прислал повтор.
_already_sent: set[tuple[int, str]] = set()

# Когда владельцу приходят сводки — по его местному времени.
DAILY_REPORT_TIME = time(9, 0)
# Пятница: неделя закончилась, а решения по ней принимать ещё не поздно.
WEEKLY_REPORT_WEEKDAY = 4
WEEKLY_REPORT_TIME = time(20, 0)


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


async def clear_sent_marks() -> None:
    """Раз в сутки: забыть отметки об отправке и брошенные разговоры."""
    _already_sent.clear()
    try:
        forgotten = await fsm_storage.forget_stale()
    except Exception:
        logger.exception("Не удалось убрать брошенные разговоры")
        return
    if forgotten:
        logger.info("Убрано брошенных разговоров: %s", forgotten)


async def send_smart_nudges(bot: Bot) -> None:
    """Одно полезное сообщение — или, чаще всего, ни одного.

    Пришло на смену двум напоминаниям по часам: вода в 16:00 и дневник в
    20:00, одним и тем же текстом каждый день. Такое сообщение перестают
    читать примерно на третий день, а заодно перестают читать все
    остальные. Теперь бот раз в час спрашивает себя, есть ли что сказать
    именно этому человеку именно сейчас, и почти всегда отвечает «нет».

    Все правила — в services/notifications.py. Здесь только отправка.
    """
    try:
        async with get_session() as session:
            planned = await notifications.due(session)
    except Exception:
        logger.exception("Не удалось собрать умные подсказки")
        return

    for user, push, day in planned:
        try:
            await bot.send_message(
                user.id,
                push.message,
                reply_markup=nudge_keyboard(target=push.target, cta=push.cta,
                                            kind=push.kind, amount=push.amount),
            )
        except Exception:
            logger.info("Не получилось отправить подсказку %s", user.id)
            continue

        # Записываем только доставленное. Иначе бюджет съедали бы сообщения,
        # которых человек не видел, — например, у заблокировавших бота.
        try:
            async with get_session() as session:
                await notifications.remember(session, push, day=day)
                await remember_suggestion(session, user.id, push.code,
                                          timezone_name=user.timezone)
        except Exception:
            logger.exception("Подсказка ушла, но не записалась: %s", user.id)


async def send_comebacks(bot: Bot) -> None:
    """Днём — тем, кто перестал заходить. Не чаще двух раз за отсутствие."""
    try:
        async with get_session() as session:
            letters = await comeback.due(session)
    except Exception:
        logger.exception("Не удалось собрать письма вернувшимся")
        return

    for letter in letters:
        key = (letter.user_id, "comeback")
        if key in _already_sent:
            continue
        try:
            await bot.send_message(letter.user_id, letter.text,
                                   reply_markup=comeback_keyboard())
            _already_sent.add(key)
        except Exception:
            logger.info("Не получилось позвать обратно %s", letter.user_id)


async def send_step_results(bot: Bot) -> None:
    """Понедельник утром — чем закончилась неделя по шагам."""
    try:
        async with get_session() as session:
            results = await step_results.due(session)
    except Exception:
        logger.exception("Не удалось собрать итоги недели по шагам")
        return

    for result in results:
        key = (result.user_id, "step_week")
        if key in _already_sent:
            continue
        try:
            await bot.send_message(result.user_id, step_results.render(result))
            _already_sent.add(key)
        except Exception:
            logger.info("Не получилось отправить итог недели %s", result.user_id)


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



async def _send_to_owner(bot: Bot, text: str) -> None:
    for admin in config.ADMIN_IDS:
        try:
            await bot.send_message(admin, text)
        except Exception:  # noqa: BLE001 — владелец мог заблокировать бота
            logger.warning("Не удалось отправить отчёт владельцу %s", admin)


async def owner_reports(bot: Bot) -> None:
    """Сводки владельцу: утренняя каждый день и недельная по пятницам.

    Время местное — то, что стоит у владельца в профиле. Поэтому проверяем
    раз в минуту, как и остальные напоминания: иначе переезд в другой пояс
    или переход на летнее время сдвигают отчёт.
    """
    if not config.ADMIN_IDS:
        return

    schedule = (
        ("owner_daily", DAILY_REPORT_TIME, None, owner_reports_text.daily),
        ("owner_weekly", WEEKLY_REPORT_TIME, WEEKLY_REPORT_WEEKDAY,
         owner_reports_text.weekly),
    )

    try:
        async with get_session() as session:
            zone = await metrics.owner_timezone(session)
            texts = []
            for key, target, weekday, build in schedule:
                if (0, key) in _already_sent:
                    continue
                if not metrics.is_time_for(zone, target, weekday=weekday):
                    continue
                texts.append((key, await build(session)))

            if texts:
                # Заодно подчищаем старые записи о расходах — раз в сутки
                # этого достаточно, и отдельная задача под это не нужна.
                await usage.cleanup(session)
    except Exception:
        logger.exception("Не удалось собрать отчёт владельцу")
        return

    for key, text in texts:
        await _send_to_owner(bot, text)
        _already_sent.add((0, key))


async def watch_health(bot: Bot) -> None:
    """Срочные проверки: диск, дневной потолок, резкий скачок расхода."""
    if not config.ADMIN_IDS:
        return
    await guard.watch(bot)


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_due_reminders, "cron", minute="*", args=[bot], id="supplements")
    # Умные подсказки: раз в час по местному времени человека. Проверяем
    # каждую минуту, но работа начинается только в тех поясах, где сейчас
    # ровно начало часа, — так же, как у всех остальных заданий.
    scheduler.add_job(send_smart_nudges, "cron", minute="*", args=[bot],
                      id="smart_nudges")
    scheduler.add_job(send_weekly_summaries, "cron", minute="*", args=[bot], id="weekly")
    # Письмо тем, кто пропал. Тоже по местному времени — раз в минуту.
    scheduler.add_job(send_comebacks, "cron", minute="*", args=[bot], id="comeback")
    # Итог недели по шагам: понедельник, местное утро — тоже раз в минуту.
    scheduler.add_job(send_step_results, "cron", minute="*", args=[bot],
                      id="step_results")
    scheduler.add_job(clear_sent_marks, "cron", hour=0, minute=1, id="cleanup")
    # Раз в день утром: предупредить об окончании и закрыть просроченные.
    scheduler.add_job(check_subscriptions, "cron", hour=6, minute=0, args=[bot],
                      id="subscriptions")
    # Сводки владельцу: время местное, поэтому проверяем каждую минуту.
    scheduler.add_job(owner_reports, "cron", minute="*", args=[bot], id="owner_reports")
    # Срочные проверки. Раз в десять минут: чаще нет смысла — диск и расход
    # так быстро не меняются, — а реже владелец узнаёт слишком поздно.
    scheduler.add_job(watch_health, "cron", minute="*/10", args=[bot], id="watch")

    if config.AUTO_UPDATE:
        # Раз в полчаса — не чаще: обновление перезапускает бота, и делать
        # это посреди разговора незачем.
        scheduler.add_job(run_update, "interval", minutes=30, id="selfupdate")
        logger.info("Автообновление включено (раз в 30 минут)")

    scheduler.start()
    logger.info("Планировщик напоминаний запущен")
    return scheduler
