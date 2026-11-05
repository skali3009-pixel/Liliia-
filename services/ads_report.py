"""Read-only сводка по рекламным меткам: пришло, анкета, оплата.

Никаких имён, Telegram ID и содержания. Только машинные метки, названия
каналов и счётчики. Запускается через `aura-run status --ads-json`.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from db import async_session_maker, engine
from models import Payment, PlategaOrder, User
from services import sources


async def collect() -> dict:
    async with async_session_maker() as session:
        starts = {
            mark: int(count) for mark, count in (await session.execute(
                select(User.first_source, func.count())
                .where(User.first_source.is_not(None))
                .group_by(User.first_source)
            )).all()
        }
        done = {
            mark: int(count) for mark, count in (await session.execute(
                select(User.first_source, func.count())
                .where(User.first_source.is_not(None),
                       User.onboarding_completed.is_(True))
                .group_by(User.first_source)
            )).all()
        }
        paid_platega = {
            mark: int(count) for mark, count in (await session.execute(
                select(User.first_source, func.count(func.distinct(User.id)))
                .join(PlategaOrder, PlategaOrder.user_id == User.id)
                .where(User.first_source.is_not(None),
                       PlategaOrder.applied_at.is_not(None))
                .group_by(User.first_source)
            )).all()
        }
        paid_legacy = {
            mark: int(count) for mark, count in (await session.execute(
                select(User.first_source, func.count(func.distinct(User.id)))
                .join(Payment, Payment.user_id == User.id)
                .where(User.first_source.is_not(None), Payment.refunded.is_(False))
                .group_by(User.first_source)
            )).all()
        }

    marks = list(sources.ADS) + [sources.DIRECT, sources.EXISTING]
    rows = []
    for mark in marks:
        rows.append({
            "mark": mark,
            "name": sources.НАЗВАНИЯ.get(mark, mark),
            "starts": starts.get(mark, 0),
            "done": done.get(mark, 0),
            "paid": max(paid_platega.get(mark, 0), paid_legacy.get(mark, 0)),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_users": sum(starts.values()),
        "rows": rows,
    }


async def main() -> None:
    try:
        print(json.dumps(await collect(), ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
