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
        "ADMIN_IDS не заполнен — без владельца платный доступ не включается"
        if not config.ADMIN_IDS
        else "выключен вручную через PAYWALL=0"
    )
    return [
        "🔓 Платный доступ: ВЫКЛЮЧЕН — ботом может пользоваться любой",
        f"   Причина: {reason}",
        f"   Пробный период людям выдаётся ({config.TRIAL_DAYS} дн.), но пока ни на что не влияет",
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

    lines = [
        f"Версия: {_git_version()}",
        "",
        *_access_mode(),
        "",
        "👥 Люди",
        f"   Заходили: {people}, дошли до конца анкеты: {onboarded}",
        f"   Сейчас на пробном: {trial_now}",
        f"   С оплаченной подпиской: {data['active']}",
        f"   Доступ закончился: {data['expired']}",
        f"   Платежей всего: {paid_ever} (звёзд за 30 дней: {data['stars_30d']})",
        "",
        *_legal_lines(),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(asyncio.run(collect()))
