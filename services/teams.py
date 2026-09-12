"""Команда: маленькая группа, которая ходит вместе.

Зачем она вообще нужна. Личный счётчик шагов человек забрасывает через
неделю, потому что смотреть в него незачем: цифра растёт, и всё. Работает
другое — что тебя видят. Поэтому здесь команда на несколько человек, общий
недельный счёт и таблица внутри неё.

Два правила, которые нужно держать в голове.

Первое: команда одна на человека. Тогда «внутри команды» означает для всех
одно и то же, и не приходится объяснять, в каком из пяти списков человек
сейчас первый.

Второе: соревнуются шагами и только шагами. Таблиц по сброшенным
килограммам в этом приложении нет и не будет — это соревнование по
голоданию. Обогнать команду можно единственным способом: пройтись.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Team, TeamMember, User
from services import steps as step_service
from utils.timeframe import DEFAULT_TIMEZONE

# Длина кода приглашения: перебирать его некому, а ссылка остаётся короткой.
CODE_LENGTH = 8

# Больше этого команда не держит: список, который не помещается на экран,
# перестают читать, и соревнование теряет смысл.
MAX_MEMBERS = 12

MAX_NAME = 40


def clean_name(value: str) -> str:
    """Название команды: одна строка, без лишних пробелов и переносов."""
    return " ".join(str(value or "").split())[:MAX_NAME]


def _code() -> str:
    return secrets.token_urlsafe(8)[:CODE_LENGTH]


@dataclass(frozen=True)
class TeamBoard:
    """Команда и её неделя."""

    id: int
    name: str
    code: str
    owner_id: int
    rows: list[step_service.Row]

    @property
    def total(self) -> int:
        return sum(row.steps for row in self.rows)

    @property
    def people(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "code": self.code,
                "owner": self.owner_id, "total": self.total,
                "people": self.people, "full": self.people >= MAX_MEMBERS,
                "rows": [row.to_dict() for row in self.rows]}


async def my_team(session: AsyncSession, user_id: int) -> Team | None:
    """Команда человека, если он в какой-то состоит."""
    team_id = (await session.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    )).scalar_one_or_none()
    if team_id is None:
        return None
    return await session.get(Team, int(team_id))


async def member_ids(session: AsyncSession, team_id: int) -> list[int]:
    return [int(value) for value in (await session.execute(
        select(TeamMember.user_id).where(TeamMember.team_id == team_id)
        .order_by(TeamMember.joined_at)
    )).scalars()]


async def create(session: AsyncSession, user_id: int, name: str) -> tuple[str, Team | None]:
    """Создать команду. Возвращает («ok»/причина отказа, команда)."""
    title = clean_name(name)
    if not title:
        return "no_name", None
    if await my_team(session, user_id) is not None:
        return "already", None

    team = Team(name=title, code=_code(), owner_id=user_id)
    session.add(team)
    await session.flush()
    session.add(TeamMember(team_id=team.id, user_id=user_id))
    await session.commit()
    return "ok", team


async def join(session: AsyncSession, user_id: int, code: str) -> tuple[str, Team | None]:
    """Вступить по коду. Возвращает («ok»/причина отказа, команда)."""
    team = (await session.execute(
        select(Team).where(Team.code == str(code or "").strip())
    )).scalar_one_or_none()
    if team is None:
        return "no_team", None

    current = await my_team(session, user_id)
    if current is not None:
        return ("same" if current.id == team.id else "already"), current

    people = int((await session.execute(
        select(func.count(TeamMember.id)).where(TeamMember.team_id == team.id)
    )).scalar_one())
    if people >= MAX_MEMBERS:
        return "full", team

    session.add(TeamMember(team_id=team.id, user_id=user_id))
    await session.commit()
    return "ok", team


async def leave(session: AsyncSession, user_id: int) -> bool:
    """Выйти из команды. Последний уходящий забирает её с собой."""
    team = await my_team(session, user_id)
    if team is None:
        return False

    await session.execute(delete(TeamMember).where(TeamMember.user_id == user_id))
    await session.flush()

    left = (await session.execute(
        select(TeamMember.user_id).where(TeamMember.team_id == team.id)
        .order_by(TeamMember.joined_at)
    )).scalars().all()

    if not left:
        # Пустая команда никому не пригодится, а её код продолжал бы работать.
        await session.execute(delete(Team).where(Team.id == team.id))
    elif team.owner_id == user_id:
        # Ушёл создатель — команда осталась бы без хозяина, и переименовать
        # её не смог бы уже никто. Передаём тому, кто вступил раньше всех.
        team.owner_id = int(left[0])
    await session.commit()
    return True


async def rename(session: AsyncSession, user_id: int, name: str) -> bool:
    """Переименовать команду. Может только тот, кто её создал."""
    team = await my_team(session, user_id)
    title = clean_name(name)
    if team is None or team.owner_id != user_id or not title:
        return False
    team.name = title
    await session.commit()
    return True


async def board(session: AsyncSession, user_id: int, *,
                timezone_name: str = DEFAULT_TIMEZONE,
                today: date | None = None) -> TeamBoard | None:
    """Команда человека с недельной таблицей внутри неё."""
    team = await my_team(session, user_id)
    if team is None:
        return None

    rows = await step_service.week_rows(
        session, await member_ids(session, team.id), me=user_id,
        timezone_name=timezone_name, today=today,
    )
    return TeamBoard(id=team.id, name=team.name, code=team.code,
                     owner_id=team.owner_id, rows=rows)


__all__ = ["CODE_LENGTH", "MAX_MEMBERS", "MAX_NAME", "TeamBoard", "board",
           "clean_name", "create", "join", "leave", "member_ids", "my_team",
           "rename"]
