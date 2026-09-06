"""Друзья: приглашения, связи и то немногое, что видно друг о друге.

Главное правило записано здесь один раз и дальше соблюдается механически:
наружу отдаётся только игровой слой. Кристаллы, уровень, серия, места мира.
Ни веса, ни замеров, ни фотографий, ни калорий, ни еды — человек делится
этим с приложением, а не со знакомыми, и подменять одно другим нельзя.

Соревнование тоже устроено осторожно. Кристаллы начисляются за обычные
полезные действия и не начисляются за голодание, минимальные калории и
перегрузку — значит и обогнать друга голоданием невозможно. Таблицы по
сброшенным килограммам здесь не будет никогда: это соревнование по
голоданию, а не по здоровью.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DayStat, Friendship, Invite, User
from utils.game import level_from_xp
from utils.timeframe import DEFAULT_TIMEZONE, today_in

# Длина кода приглашения. Восьми символов достаточно: перебирать их некому,
# а ссылка остаётся короткой.
CODE_LENGTH = 8

# Больше этого числа друзей приложение не держит: список, который не
# помещается на экран, никто не читает, а соревнование теряет смысл.
MAX_FRIENDS = 20

# За сколько дней считается общий счёт.
WEEK_DAYS = 7


@dataclass(frozen=True)
class FriendCard:
    """Что один человек видит о другом. Только игровой слой."""

    user_id: int
    name: str
    level: int
    crystals: int
    week_crystals: int
    streak: int
    is_me: bool = False

    def to_dict(self) -> dict:
        return {"user_id": self.user_id, "name": self.name, "level": self.level,
                "crystals": self.crystals, "week": self.week_crystals,
                "streak": self.streak, "me": self.is_me}


async def invite_code(session: AsyncSession, user_id: int, *, renew: bool = False) -> str:
    """Личный код приглашения. `renew` выдаёт новый — так отзывают старую ссылку."""
    row = (await session.execute(
        select(Invite).where(Invite.user_id == user_id)
    )).scalar_one_or_none()

    if row is None:
        row = Invite(user_id=user_id, code=secrets.token_urlsafe(6)[:CODE_LENGTH])
        session.add(row)
    elif renew:
        row.code = secrets.token_urlsafe(6)[:CODE_LENGTH]
    await session.commit()
    return row.code


async def owner_of(session: AsyncSession, code: str) -> int | None:
    row = (await session.execute(
        select(Invite).where(Invite.code == code)
    )).scalar_one_or_none()
    return row.user_id if row else None


async def are_friends(session: AsyncSession, user_id: int, other_id: int) -> bool:
    return bool((await session.execute(
        select(Friendship.id).where(Friendship.user_id == user_id,
                                    Friendship.friend_id == other_id)
    )).scalar_one_or_none())


async def count(session: AsyncSession, user_id: int) -> int:
    return int((await session.execute(
        select(func.count()).select_from(Friendship).where(Friendship.user_id == user_id)
    )).scalar_one())


async def connect(session: AsyncSession, user_id: int, other_id: int) -> str:
    """Подружить двоих. Возвращает короткое объяснение исхода."""
    if user_id == other_id:
        return "self"
    if await are_friends(session, user_id, other_id):
        return "already"
    if await count(session, user_id) >= MAX_FRIENDS:
        return "full"
    if await count(session, other_id) >= MAX_FRIENDS:
        return "their_full"

    # Две строки: список друзей — это выборка по одному полю, а разрыв с
    # любой стороны убирает обе.
    session.add(Friendship(user_id=user_id, friend_id=other_id))
    session.add(Friendship(user_id=other_id, friend_id=user_id))
    await session.commit()
    return "ok"


async def disconnect(session: AsyncSession, user_id: int, other_id: int) -> None:
    """Разорвать связь. С любой стороны и без вопросов ко второму."""
    await session.execute(delete(Friendship).where(
        Friendship.user_id.in_([user_id, other_id]),
        Friendship.friend_id.in_([user_id, other_id]),
    ))
    await session.commit()


async def _crystals(session: AsyncSession, user_ids: list[int], *,
                    since=None) -> dict[int, int]:
    """Кристаллы каждого — всего или за период."""
    if not user_ids:
        return {}
    stmt = select(DayStat.user_id, func.coalesce(func.sum(DayStat.xp + DayStat.bonus), 0))
    stmt = stmt.where(DayStat.user_id.in_(user_ids))
    if since is not None:
        stmt = stmt.where(DayStat.day >= since)
    rows = (await session.execute(stmt.group_by(DayStat.user_id))).all()
    return {user_id: int(total) for user_id, total in rows}


async def _streaks(session: AsyncSession, user_ids: list[int], today) -> dict[int, int]:
    """Серии всех сразу: по одному запросу вместо запроса на друга."""
    if not user_ids:
        return {}
    rows = (await session.execute(
        select(DayStat.user_id, DayStat.day).where(
            DayStat.user_id.in_(user_ids), DayStat.xp > 0)
    )).all()

    days: dict[int, set] = {}
    for user_id, day in rows:
        days.setdefault(user_id, set()).add(day)

    out = {}
    for user_id, seen in days.items():
        cursor, streak = today, 0
        if cursor not in seen:
            cursor -= timedelta(days=1)
        while cursor in seen:
            streak += 1
            cursor -= timedelta(days=1)
        out[user_id] = streak
    return out


async def board(session: AsyncSession, user_id: int, *,
                timezone_name: str = DEFAULT_TIMEZONE) -> list[FriendCard]:
    """Человек и его друзья, по кристаллам за неделю.

    Сравниваем именно кристаллы: их дают за обычные полезные действия и не
    дают за голодание. Обогнать друга, перестав есть, здесь нельзя.
    """
    friend_ids = list((await session.execute(
        select(Friendship.friend_id).where(Friendship.user_id == user_id)
    )).scalars())
    everyone = [user_id, *friend_ids]

    today = today_in(timezone_name)
    total = await _crystals(session, everyone)
    week = await _crystals(session, everyone, since=today - timedelta(days=WEEK_DAYS - 1))
    streaks = await _streaks(session, everyone, today)

    names = {
        row.id: (row.full_name or "").split(" ")[0] or "Без имени"
        for row in (await session.execute(
            select(User).where(User.id.in_(everyone)))).scalars()
    }

    cards = [
        FriendCard(
            user_id=who,
            name=names.get(who, "Без имени"),
            level=level_from_xp(total.get(who, 0)).number,
            crystals=total.get(who, 0),
            week_crystals=week.get(who, 0),
            streak=streaks.get(who, 0),
            is_me=who == user_id,
        )
        for who in everyone
    ]
    cards.sort(key=lambda card: (-card.week_crystals, -card.crystals, card.name))
    return cards


__all__ = ["CODE_LENGTH", "FriendCard", "MAX_FRIENDS", "WEEK_DAYS", "are_friends",
           "board", "connect", "count", "disconnect", "invite_code", "owner_of"]
