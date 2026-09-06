"""Что сейчас с ботом: режим доступа, люди, документы, версия.

Отвечает на вопрос «открыт бот всем или уже закрыт?» одной командой, без
лазанья по .env и базе. Запускается скриптом status.sh.
"""

from __future__ import annotations

import asyncio
import subprocess

from sqlalchemy import func, select

import config
from db import async_session_maker
from models import Payment, Subscription, SubscriptionStatus, User
from services.legal import LEGAL_VERSION
from services.subscriptions import now, stats

YES, NO = "да", "нет"


def _git_version() -> str:
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%h · %cd", "--date=format:%d.%m %H:%M"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or "неизвестно"
    except (OSError, subprocess.SubprocessError):
        return "неизвестно"


def _access_mode() -> list[str]:
    """Главный вопрос: пускает бот всех подряд или только по подписке."""
    if config.PAYWALL:
        return [
            "🔒 Платный доступ: ВКЛЮЧЁН",
            f"   Пробный период: {config.TRIAL_DAYS} дн., дальше {config.SUB_PRICE_STARS} ⭐ в месяц",
            f"   Владельцы: {', '.join(str(i) for i in sorted(config.ADMIN_IDS))}",
        ]

    reason = (
        "в .env стоит PAYWALL=1, но не заполнен ADMIN_IDS — без владельца "
        "оплата не включается"
        if not config.ADMIN_IDS
        else "так и задумано: бот дорабатывается и бесплатен для всех"
    )
    return [
        "🔓 Платный доступ: ВЫКЛЮЧЕН — ботом может пользоваться любой",
        f"   Причина: {reason}",
        f"   Пробный период людям выдаётся ({config.TRIAL_DAYS} дн.), но пока ни на что не влияет",
        "   Включить оплату, когда решишь: bash set-paywall.sh on",
    ]


def _art_lines() -> list[str]:
    """Какие фоновые картинки не скачались.

    Приложение без них не ломается — на месте картинки остаётся соседний
    арт или градиент, — но знать об этом полезно.
    """
    from services.artwork import missing

    absent = missing()
    if not absent:
        return ["🖼 Картинки: все на месте"]
    return [
        f"🖼 Картинки: не хватает {len(absent)} — {', '.join(absent)}",
        "   Экран покажет соседний арт. Докачать: bash fetch-art.sh",
    ]


def _legal_lines() -> list[str]:
    filled = all((config.LEGAL_OWNER, config.LEGAL_EMAIL))
    lines = [f"📄 Документы: редакция {LEGAL_VERSION}, реквизиты заполнены — "
             f"{YES if filled else NO}"]
    if not filled:
        lines.append("   Заполнить: bash set-legal.sh — спросит имя, реквизиты и почту")
    if not config.WEBAPP_URL:
        lines.append("   Нет WEBAPP_URL — ссылки на документы в боте не показываются")
    return lines


async def collect() -> str:
    async with async_session_maker() as session:
        people = int((await session.execute(
            select(func.count()).select_from(User)
        )).scalar_one())
        onboarded = int((await session.execute(
            select(func.count()).select_from(User).where(User.onboarding_completed.is_(True))
        )).scalar_one())
        data = await stats(session)
        paid_ever = int((await session.execute(
            select(func.count()).select_from(Payment)
        )).scalar_one())
        trial_now = int((await session.execute(
            select(func.count()).select_from(Subscription).where(
                Subscription.status == SubscriptionStatus.TRIAL,
                Subscription.expires_at > now(),
            )
        )).scalar_one())

    from services import usage as usage_service
    from utils.disk import usage as disk_usage

    async with async_session_maker() as session:
        spend = await usage_service.spent_today(session)
    disk = disk_usage()

    lines = [
        f"Версия: {_git_version()}",
        "",
        *_access_mode(),
        "",
        "👥 Люди",
        f"   Заходили: {people}, дошли до конца анкеты: {onboarded}",
        f"   Сейчас на пробном: {trial_now}",
        f"   С бесплатным доступом навсегда: {data['lifetime']}",
        f"   С оплаченной подпиской: {data['active']}",
        f"   Доступ закончился: {data['expired']}",
        f"   Платежей всего: {paid_ever} (звёзд за 30 дней: {data['stars_30d']})",
        "",
        "💰 Расход на модель сегодня",
        f"   Потрачено: {spend.total_usd:.2f} $ из {config.DAILY_COST_LIMIT_USD:.0f} $ "
        f"({spend.calls} запросов)",
        f"   Осталось до потолка: {spend.left_usd:.2f} $",
        f"   Модель для фото: {config.VISION_MODEL}",
        "",
        "💾 Диск",
        f"   Занято {disk.percent}% — {disk.used_gb} из {disk.total_gb} ГБ, "
        f"свободно {disk.free_gb} ГБ",
        "",
        *_art_lines(),
        "",
        *_legal_lines(),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(asyncio.run(collect()))
