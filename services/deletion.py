"""Удаление человека: то, чего база не может сделать сама.

Почти всё убирается каскадом — записи еды, воды, шагов, замеров исчезают
вместе со строкой пользователя. Но две связи каскадом не описываются, и
именно они переживают удаление.

Первая: дружба хранится двумя строками, и в обратной ссылку на человека
держит не внешний ключ, а просто число. Удалили одного — у второго в списке
остаётся строка, указывающая в никуда.

Вторая: приглашение. Строка «кто кого привёл» держит приведённого внешним
ключом, а приглашающую — просто числом, и по той же причине: удаление своих
данных одним человеком не должно стирать историю другого. Но когда уходит
сама приглашающая, её номер обязан уйти вместе с ней: это её данные, а не
чужие.

Третья: команда. Участие исчезает каскадом, а сама команда — нет. Если
уходит её создатель, команда остаётся без хозяина, и переименовать её не
может уже никто. Если уходит последний участник, пустая команда живёт вечно
вместе с работающим кодом приглашения.

Поэтому удаление — не одна строка `session.delete(user)`, а короткий список
того, что надо прибрать руками. Человек, нажавший «удалить мои данные»,
вправе рассчитывать, что его действительно нигде нет.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Friendship, Referral, Team, TeamMember, User

logger = logging.getLogger(__name__)


async def _forget_friendships(session: AsyncSession, user_id: int) -> int:
    """Убрать обе стороны дружбы, включая ту, что каскад не заберёт."""
    result = await session.execute(
        delete(Friendship).where(Friendship.friend_id == user_id))
    return result.rowcount or 0


async def _forget_invites(session: AsyncSession, user_id: int) -> int:
    """Убрать строки «кто кого привёл» с обеих сторон.

    Приглашающая сторона внешним ключом не защищена вовсе — её надо убирать
    руками. Приведённую забрал бы каскад, но здесь он не полагается ни на
    что: каскад исполняет база, а SQLite без отдельной настройки внешние
    ключи не проверяет совсем. Обещание «тебя нигде нет» не может зависеть
    от того, какая база стоит под ботом, — тем более что проверяется оно на
    той, где каскада нет.
    """
    result = await session.execute(delete(Referral).where(
        (Referral.inviter_id == user_id) | (Referral.invited_id == user_id)))
    return result.rowcount or 0


async def _leave_team(session: AsyncSession, user_id: int) -> None:
    """Вывести из команды: передать её или распустить, если никого не осталось."""
    row = (await session.execute(
        select(TeamMember).where(TeamMember.user_id == user_id)
    )).scalar_one_or_none()
    if row is None:
        return

    team = await session.get(Team, row.team_id)
    await session.execute(delete(TeamMember).where(TeamMember.user_id == user_id))
    await session.flush()
    if team is None:
        return

    left = (await session.execute(
        select(TeamMember.user_id).where(TeamMember.team_id == team.id)
        .order_by(TeamMember.joined_at)
    )).scalars().all()

    if not left:
        # Пустая команда никому не пригодится, а код приглашения работал бы.
        await session.execute(delete(Team).where(Team.id == team.id))
    elif team.owner_id == user_id:
        # Иначе команда остаётся без хозяина и её нельзя даже переименовать.
        team.owner_id = int(left[0])


async def purge(session: AsyncSession, user_id: int) -> bool:
    """Удалить человека и всё, что о нём осталось. False — если его уже нет."""
    user = await session.get(User, user_id)
    if user is None:
        return False

    forgotten = await _forget_friendships(session, user_id)
    invites = await _forget_invites(session, user_id)
    await _leave_team(session, user_id)

    await session.delete(user)
    await session.commit()
    logger.info("Удалён пользователь %s (обратных дружб: %d, приглашений: %d)",
                user_id, forgotten, invites)
    return True


async def orphan_friendships(session: AsyncSession) -> int:
    """Сколько дружб указывает на людей, которых уже нет. Нужно проверкам."""
    known = select(User.id)
    return int((await session.execute(
        select(func.count(Friendship.id)).where(Friendship.friend_id.not_in(known))
    )).scalar_one())


__all__ = ["orphan_friendships", "purge"]
