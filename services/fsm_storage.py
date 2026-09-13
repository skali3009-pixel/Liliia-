"""Незаконченный разговор переживает перезапуск бота.

Пока состояние жило только в памяти, всякий перезапуск стирал его. Бот
обновляется сам раз в полчаса, а ещё бывают сбои и переустановки — и
человек, который сфотографировал еду и отвлёкся на минуту, возвращался к
карточке, жал «Сохранить» и не получал ничего. Ни ошибки, ни записи:
кнопка просто крутилась, пока Telegram не сдавался. Так это и выглядит
снаружи — «подвисает».

Та же беда была и с недописанной анкетой, и с наполовину введённым весом.

Здесь состояние лежит в той же базе, где всё остальное. Отдельного Redis
ради этого заводить не надо: разговоров немного, строка на человека,
и читаются они по первичному ключу.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from sqlalchemy import delete, select

from db import get_session
from models import FsmState

logger = logging.getLogger(__name__)

# Брошенные разговоры не хранятся вечно: анкета, начатая полгода назад,
# человеку уже не нужна, а строка в базе — да.
STALE_DAYS = 14


def _key(key: StorageKey) -> str:
    """Ключ разговора одной строкой: бот, чат, человек и «ветка»."""
    parts = [key.bot_id, key.chat_id, key.user_id, key.thread_id or 0,
             key.business_connection_id or "", key.destiny]
    return ":".join(str(part) for part in parts)


class DatabaseStorage(BaseStorage):
    """Хранилище состояний FSM в основной базе."""

    async def _row(self, session, key: StorageKey) -> FsmState | None:
        return await session.get(FsmState, _key(key))

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        name = state.state if isinstance(state, State) else state
        async with get_session() as session:
            row = await self._row(session, key)
            if row is None:
                if name is None:
                    return              # нечего забывать
                row = FsmState(key=_key(key), data="{}")
                session.add(row)
            row.state = name
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with get_session() as session:
            row = await self._row(session, key)
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        async with get_session() as session:
            row = await self._row(session, key)
            if row is None:
                if not data:
                    return
                row = FsmState(key=_key(key), data="{}")
                session.add(row)
            row.data = json.dumps(data, ensure_ascii=False)
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with get_session() as session:
            row = await self._row(session, key)
        if row is None or not row.data:
            return {}
        try:
            loaded = json.loads(row.data)
        except ValueError:
            # Испорченная строка не должна ломать разговор: лучше начать
            # заново, чем не отвечать вовсе.
            logger.warning("Не разобрал сохранённое состояние %s", row.key)
            return {}
        return loaded if isinstance(loaded, dict) else {}

    async def close(self) -> None:
        return None


async def forget_stale(*, now_utc: datetime | None = None) -> int:
    """Убрать давно брошенные разговоры. Возвращает число удалённых."""
    moment = now_utc or datetime.now(timezone.utc)
    async with get_session() as session:
        edge = moment - timedelta(days=STALE_DAYS)
        rows = (await session.execute(
            select(FsmState.key).where(FsmState.updated_at < edge)
        )).scalars().all()
        if rows:
            await session.execute(delete(FsmState).where(FsmState.key.in_(rows)))
            await session.commit()
    return len(rows)


__all__ = ["DatabaseStorage", "STALE_DAYS", "forget_stale"]
