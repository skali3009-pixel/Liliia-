"""One final factual report per expired paid period; no win-back sequence."""
from datetime import timedelta
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import select

from db import get_session
from models import Subscription, SubscriptionSource, User, Meal, WorkoutLog, BodyMeasurement, WaterLog
from services.subscriptions import now, _aware, check_access
from utils.timeframe import to_local

logger = logging.getLogger(__name__)


async def report(session, user, end):
    # The current product is a 30-day subscription. Describe the window
    # explicitly, including for a manually granted or extended access period.
    start = end - timedelta(days=30)
    meals = list((await session.scalars(select(Meal).where(
        Meal.user_id == user.id, Meal.logged_at >= start, Meal.logged_at < end
    ))).all())
    workouts = list((await session.scalars(select(WorkoutLog).where(
        WorkoutLog.user_id == user.id, WorkoutLog.completed_at >= start,
        WorkoutLog.completed_at < end
    ))).all())
    weights = list((await session.scalars(select(BodyMeasurement).where(
        BodyMeasurement.user_id == user.id, BodyMeasurement.measured_at >= start,
        BodyMeasurement.measured_at < end, BodyMeasurement.weight_kg.is_not(None)
    ).order_by(BodyMeasurement.measured_at))).all())
    days = len({to_local(m.logged_at, user.timezone).date() for m in meals})
    water = list((await session.scalars(select(WaterLog).where(
        WaterLog.user_id == user.id, WaterLog.logged_at >= start, WaterLog.logged_at < end
    ))).all())
    water_days = len({to_local(w.logged_at, user.timezone).date() for w in water})
    lines = [
        "🔒 Подписка AURA закончилась.",
        f"📊 Твои записи за последние 30 дней "
        f"({to_local(start, user.timezone):%d.%m} — {to_local(end, user.timezone):%d.%m}):",
        f"🥗 Питание: {len(meals)} записей за {days} дн.",
        f"💧 Вода отмечена за {water_days} дн.",
        f"🏋️ Выполнено упражнений/записей активности: {len(workouts)}. "
        f"Отмеченное время: {round(sum(w.duration_minutes or 0 for w in workouts))} мин.",
    ]
    if len(weights) >= 2:
        first, last = weights[0].weight_kg, weights[-1].weight_kg
        lines.append(f"⚖️ Вес по замерам: {first:g} → {last:g} кг "
                     f"({last - first:+.1f} кг).")
    else:
        lines.append("⚖️ Для сравнения веса нужно хотя бы два замера — пока данных недостаточно.")
    if not meals and not workouts and not weights and not water:
        lines.append("За этот период записей нет. Оценить результат по данным AURA пока нельзя.")
    lines.append("Все записи сохранены. Напоминания и плановые сообщения остановлены. "
                 "Если захочешь продолжить — /subscription. Автосписаний нет.")
    return "\n\n".join(lines)


async def send_final_reports(bot):
    async with get_session() as session:
        ids = list((await session.scalars(select(Subscription.user_id).where(
            Subscription.expires_at <= now(),
            Subscription.expires_at > now() - timedelta(days=1),
            Subscription.source != SubscriptionSource.TRIAL,
            Subscription.lifetime.is_(False),
        ))).all())
    for user_id in ids:
        from services.bot_migration import reachable
        if not await reachable(user_id):
            continue
        # Lock the same subscription row used by payment settlement. Renewals
        # cannot race the access check and final message.
        async with get_session() as session:
            sub = (await session.execute(select(Subscription).where(
                Subscription.user_id == user_id
            ).with_for_update())).scalar_one_or_none()
            if not sub or (await check_access(session, user_id)).allowed:
                continue
            end = _aware(sub.expires_at)
            if _aware(sub.expiry_notice_for) == end:
                continue
            user = await session.get(User, user_id)
            if not user:
                continue
            text = await report(session, user, end)
            try:
                await bot.send_message(user_id, text)
            except TelegramRetryAfter:
                # Telegram explicitly rejected this attempt; retry next tick.
                continue
            except (TelegramBadRequest, TelegramForbiddenError):
                logger.info("Final report unavailable for user %s", user_id)
            except Exception:
                # Timeout may mean delivered. Do not spam by blindly retrying.
                logger.exception("Final report delivery uncertain for user %s", user_id)
            sub.expiry_notice_for = end
            await session.commit()
