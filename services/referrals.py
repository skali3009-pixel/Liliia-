"""Приглашения с наградой: кто кого привёл и сколько дней за это дают.

Механика собрана целиком, но **включается вместе с оплатой** и не раньше.
Причина простая: награда здесь — дни доступа, а пока доступ бесплатен для
всех, «дарим тебе неделю» означает подарок того, что и так ничего не стоит.
Человек получит сообщение и не поймёт, за что спасибо, а слово «подарок»
обесценится до того, как им впервые воспользуются. Поэтому весь начисляющий
код молчит, пока выключен `PAYWALL`.

Что при этом работает всегда: запись о том, кто кого привёл. Она не награда,
она память. Соберётся она сама, без единого действия, и в тот день, когда
оплату включат, история уже будет.

Две награды устроены по-разному, и это не мелочь.

- **За дошедшую до конца анкеты** — обеим по неделе, но не больше чем за
  пятерых. Регистрация бесплатна, и без потолка десять знакомых, нажавших
  «Начать», превращаются в два месяца бесплатного доступа за пять минут.
- **За первую оплату приведённой** — две недели, и потолка нет вовсе. Эта
  награда выдаётся из денег, которые уже пришли; ограничивать её значит
  наказывать за то, что человек приводит платящих людей.

Одно правило сверху обоих: «привела» записывается только тому, кто ещё не
заполнил анкету. Иначе две подруги обменяются ссылками и начислят друг другу
по неделе, ничего не сделав, — а это не приглашение, а вторая касса.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import Payment, Referral, SubscriptionSource, User
from services.subscriptions import activate, get_subscription, is_admin

logger = logging.getLogger(__name__)

# Ссылка тут та же самая, по которой заводится дружба, — второй человеку не
# надо, и объяснять разницу между «позвать в друзья» и «позвать в бота» не
# надо тоже. Поэтому и приставка берётся у друзей, а не пишется заново.

# Сколько дней даётся, когда приведённая дошла до конца анкеты.
SIGNUP_DAYS_INVITER = 7
SIGNUP_DAYS_NEWCOMER = 7

# Сколько даётся за первую оплату приведённой.
PAYMENT_DAYS_INVITER = 14

# За скольких дают награду «за анкету». Дальше приглашать можно сколько
# угодно, но бесплатные дни за бесплатное действие кончаются.
SIGNUP_LIMIT = 5


def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Summary:
    """Что человек видит про свои приглашения."""

    invited: int          # сколько пришло по ссылке
    signed_up: int        # сколько из них дошло до конца анкеты
    paid: int             # сколько из них заплатило
    days_earned: int      # сколько дней уже начислено
    signups_left: int     # сколько наград «за анкету» ещё осталось


async def remember(session: AsyncSession, invited_id: int, args: str | None) -> bool:
    """Записать, кто привёл этого человека. Работает и при выключенной оплате.

    Запись делается один раз за всё время и только тому, кто ещё не заполнил
    анкету: пришедший по ссылке старожил — это не приведённый человек.
    """
    from services import friends

    code = friends.code_from_args(args)
    if code is None:
        return False

    inviter = await friends.owner_of(session, code)
    if inviter is None or inviter == invited_id:
        return False

    invited = await session.get(User, invited_id)
    if invited is None or invited.onboarding_completed:
        return False

    existing = (await session.execute(
        select(Referral).where(Referral.invited_id == invited_id)
    )).scalar_one_or_none()
    if existing is not None:
        return False

    session.add(Referral(invited_id=invited_id, inviter_id=inviter))
    await session.commit()
    logger.info("Приглашение записано: %s привела %s", inviter, invited_id)
    return True


async def _row(session: AsyncSession, invited_id: int) -> Referral | None:
    return (await session.execute(
        select(Referral).where(Referral.invited_id == invited_id)
    )).scalar_one_or_none()


async def _can_receive(session: AsyncSession, user_id: int) -> bool:
    """Есть ли смысл давать этому человеку дни.

    У владельца доступ всегда, а у тех, кто пользовался ботом до платы,
    стоит «бесплатно навсегда» — им дни не добавляют ничего. Молча записать
    начисление такому человеку значит соврать ему в сообщении и потратить
    одну из пяти наград впустую.
    """
    if is_admin(user_id):
        return False
    subscription = await get_subscription(session, user_id)
    return not (subscription is not None and subscription.lifetime)


async def reward_signup(session: AsyncSession, invited_id: int) -> tuple[int, int, int]:
    """Награда за дошедшую до конца анкеты.

    Возвращает (кто привёл, дней приглашающей, дней новенькой). Нули значат,
    что начислять нечего или незачем.
    """
    if not config.PAYWALL:
        return (0, 0, 0)

    row = await _row(session, invited_id)
    if row is None or row.signup_rewarded_at is not None:
        return (0, 0, 0)

    rewarded = (await session.execute(
        select(func.count()).select_from(Referral).where(
            Referral.inviter_id == row.inviter_id,
            Referral.signup_rewarded_at.is_not(None),
        )
    )).scalar_one()
    if rewarded >= SIGNUP_LIMIT:
        return (row.inviter_id, 0, 0)

    to_inviter = SIGNUP_DAYS_INVITER if await _can_receive(session, row.inviter_id) else 0
    to_newcomer = SIGNUP_DAYS_NEWCOMER if await _can_receive(session, invited_id) else 0
    if not to_inviter and not to_newcomer:
        return (row.inviter_id, 0, 0)

    if to_inviter:
        await activate(session, row.inviter_id, days=to_inviter,
                       source=SubscriptionSource.MANUAL)
    if to_newcomer:
        await activate(session, invited_id, days=to_newcomer,
                       source=SubscriptionSource.MANUAL)

    row.signup_rewarded_at = now()
    await session.commit()
    logger.info("Награда за анкету: %s получила %d дн., %s — %d дн.",
                row.inviter_id, to_inviter, invited_id, to_newcomer)
    return (row.inviter_id, to_inviter, to_newcomer)


async def reward_payment(session: AsyncSession, invited_id: int) -> tuple[int, int]:
    """Награда приглашающей за первую оплату приведённой.

    Возвращает (кто привёл, дней). Платит один раз за человека, сколько бы
    раз тот ни продлевал подписку: награда за приведённого платящего, а не
    процент с каждого платежа.
    """
    if not config.PAYWALL:
        return (0, 0)

    row = await _row(session, invited_id)
    if row is None or row.payment_rewarded_at is not None:
        return (0, 0)

    days = PAYMENT_DAYS_INVITER if await _can_receive(session, row.inviter_id) else 0
    if days:
        await activate(session, row.inviter_id, days=days,
                       source=SubscriptionSource.MANUAL)

    row.payment_rewarded_at = now()
    await session.commit()
    logger.info("Награда за оплату: %s получила %d дн. за %s",
                row.inviter_id, days, invited_id)
    return (row.inviter_id, days)


async def summary(session: AsyncSession, user_id: int) -> Summary:
    """Сводка по приглашениям одного человека."""
    rows = list((await session.execute(
        select(Referral).where(Referral.inviter_id == user_id)
    )).scalars())
    ids = [r.invited_id for r in rows]

    # «Дошла до анкеты» и «заплатила» считаются по самим людям, а не по
    # отметкам о начислении. Пока оплата выключена, начислений нет вовсе, и
    # сводка по отметкам показывала бы нули при живых приведённых подругах.
    signed_up = 0
    paid = 0
    if ids:
        signed_up = (await session.execute(
            select(func.count()).select_from(User).where(
                User.id.in_(ids), User.onboarding_completed.is_(True)
            )
        )).scalar_one()
        paid = (await session.execute(
            select(func.count(func.distinct(Payment.user_id))).where(
                Payment.user_id.in_(ids)
            )
        )).scalar_one()

    # А начислено — ровно по отметкам: это деньги, и врать в них нельзя.
    rewarded_signups = sum(1 for r in rows if r.signup_rewarded_at is not None)
    rewarded_payments = sum(1 for r in rows if r.payment_rewarded_at is not None)
    days = (rewarded_signups * SIGNUP_DAYS_INVITER
            + rewarded_payments * PAYMENT_DAYS_INVITER)

    return Summary(
        invited=len(rows),
        signed_up=signed_up,
        paid=paid,
        days_earned=days,
        signups_left=max(0, SIGNUP_LIMIT - rewarded_signups),
    )
