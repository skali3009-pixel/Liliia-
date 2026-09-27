"""Как человек показан в общей таблице шагов.

Общая таблица — это все, кто записал шаги на неделе, то есть в основном
незнакомые друг другу люди. Настоящее имя из Telegram там по умолчанию не
показывается: псевдоним вида «Лиловый гепард 27» постоянен для человека
(чтобы видеть себя и соседей неделя к неделе), но не выводится из имени и
не раскрывает номер в Telegram. Имя — только по выбору самого человека.

В команде и у друзей имена остаются: туда люди вошли сами, зная, с кем.
"""

from __future__ import annotations

import hashlib
import hmac

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import BoardPrefs

ПРИЛАГАТЕЛЬНЫЕ = ("Лиловый", "Золотой", "Тихий", "Быстрый", "Ночной", "Лунный",
                  "Звёздный", "Лёгкий", "Смелый", "Бодрый", "Мягкий", "Ясный")
ЗВЕРИ = ("гепард", "лис", "кит", "ёж", "сокол", "олень", "барс", "кот",
         "журавль", "лось", "дельфин", "енот")


def pseudonym(user_id: int) -> str:
    """Постоянный псевдоним. Ключ — секрет бота: по псевдониму номер не узнать."""
    key = (config.BOT_TOKEN or "aura").encode()
    digest = hmac.new(key, str(user_id).encode(), hashlib.sha256).digest()
    return (f"{ПРИЛАГАТЕЛЬНЫЕ[digest[0] % len(ПРИЛАГАТЕЛЬНЫЕ)]} "
            f"{ЗВЕРИ[digest[1] % len(ЗВЕРИ)]} {10 + digest[2] % 90}")


async def prefs_for(session: AsyncSession, user_ids) -> dict[int, BoardPrefs]:
    ids = list(user_ids)
    if not ids:
        return {}
    rows = (await session.execute(
        select(BoardPrefs).where(BoardPrefs.user_id.in_(ids)))).scalars().all()
    return {row.user_id: row for row in rows}


async def mine(session: AsyncSession, user_id: int) -> dict:
    row = await session.get(BoardPrefs, user_id)
    return {"show_name": bool(row and row.show_name),
            "hidden": bool(row and row.hidden),
            "pseudonym": pseudonym(user_id)}


async def set_mine(session: AsyncSession, user_id: int, *,
                   show_name: bool | None = None, hidden: bool | None = None) -> dict:
    row = await session.get(BoardPrefs, user_id)
    if row is None:
        row = BoardPrefs(user_id=user_id, show_name=False, hidden=False)
        session.add(row)
    if show_name is not None:
        row.show_name = bool(show_name)
    if hidden is not None:
        row.hidden = bool(hidden)
    await session.commit()
    return await mine(session, user_id)


__all__ = ["mine", "prefs_for", "pseudonym", "set_mine"]
