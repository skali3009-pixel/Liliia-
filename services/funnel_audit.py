"""Read-only воронка: источники, шаги анкеты, кнопки, счета, оплаты.

Без имён, Telegram ID и содержания. Запуск: `aura-run status --funnel-json`.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from db import async_session_maker, engine
from models import ButtonPress, FsmState, MarketingEvent, PlategaOrder, User
from services import sources

TZ = ZoneInfo("Europe/Moscow")
STATE_LABELS = {
    "OnboardingStates:interest": "Интерес",
    "OnboardingStates:name": "Имя",
    "OnboardingStates:gender": "Пол",
    "OnboardingStates:age": "Возраст",
    "OnboardingStates:height": "Рост",
    "OnboardingStates:current_weight": "Текущий вес",
    "OnboardingStates:target_weight": "Целевой вес",
    "OnboardingStates:activity_level": "Активность",
    "OnboardingStates:goal": "Цель",
    "OnboardingStates:diet_type": "Питание",
    "OnboardingStates:training_place": "Место тренировок",
    "OnboardingStates:training_pace": "Ритм",
    "OnboardingStates:allergies": "Аллергии",
    "OnboardingStates:summary": "Сводка",
}
EVENT_LABELS = {
    "bot_start": "Запуск бота",
    "profile_completed": "Анкета завершена",
    "first_action_completed": "Первое полезное действие",
    "action_completed": "Полезное действие",
    "active_day": "Активный день",
    "demo_started": "Примерка еды: начало",
    "demo_done": "Примерка еды: разбор",
}


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _day(value):
    return _aware(value).astimezone(TZ).date() if value else None


async def collect() -> dict:
    async with async_session_maker() as session:
        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        users = (await session.execute(select(
            User.id, User.created_at, User.onboarding_completed, User.first_source
        ))).all()
        events = (await session.execute(select(
            MarketingEvent.user_id, MarketingEvent.event, MarketingEvent.kind,
            MarketingEvent.day, MarketingEvent.count
        ))).all()
        buttons = (await session.execute(select(
            ButtonPress.user_id, ButtonPress.button, ButtonPress.day, ButtonPress.count
        ))).all()
        states = (await session.execute(select(
            FsmState.key, FsmState.state, FsmState.updated_at
        ))).all()
        orders = (await session.execute(select(
            PlategaOrder.id, PlategaOrder.user_id, PlategaOrder.status,
            PlategaOrder.created_at, PlategaOrder.applied_at
        ))).all()

    by_id = {uid: (created, completed, source)
             for uid, created, completed, source in users}
    completed = {uid for uid, (_, done, _) in by_id.items() if done}
    paid = {order.user_id for order in orders if order.applied_at is not None}
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Последнее состояние анкеты на человека; нужны только незавершённые.
    latest_state = {}
    for key, state, updated in states:
        parts = str(key).split(":")
        if len(parts) < 3 or not parts[2].isdigit():
            continue
        uid = int(parts[2])
        if uid in completed:
            continue
        moment = _aware(updated) or datetime.min.replace(tzinfo=timezone.utc)
        if uid not in latest_state or moment > latest_state[uid][0]:
            latest_state[uid] = (moment, state)

    incomplete_states = Counter()
    for uid, (_, done, _) in by_id.items():
        if done:
            continue
        state = latest_state.get(uid, (None, None))[1]
        label = STATE_LABELS.get(state, state or "Нет активного шага")
        incomplete_states[label] += 1

    by_source = defaultdict(lambda: {"starts": 0, "completed": 0, "orders": 0, "paid": 0})
    for uid, (_, done, source) in by_id.items():
        mark = source or "no_source"
        by_source[mark]["starts"] += 1
        if done:
            by_source[mark]["completed"] += 1
    for order in orders:
        source = by_id.get(order.user_id, (None, None, None))[2] or "no_source"
        by_source[source]["orders"] += 1
        if order.applied_at is not None:
            by_source[source]["paid"] += 1

    by_day = defaultdict(lambda: {"starts": 0, "completed": 0, "orders": 0, "paid": 0})
    for uid, (created, done, _) in by_id.items():
        day = _day(created)
        if day:
            by_day[day]["starts"] += 1
            if done:
                by_day[day]["completed"] += 1
    for order in orders:
        day = _day(order.created_at)
        if day:
            by_day[day]["orders"] += 1
            if order.applied_at is not None:
                by_day[day]["paid"] += 1

    event_stats = defaultdict(lambda: {"count": 0, "people": set()})
    nudge_kinds = Counter()
    for uid, event, kind, day, count in events:
        key = EVENT_LABELS.get(event, event)
        event_stats[key]["count"] += int(count or 0)
        event_stats[key]["people"].add(uid)
        if event == "pay_nudge":
            nudge_kinds[kind] += int(count or 0)

    button_stats = defaultdict(lambda: {"presses": 0, "people": set()})
    for uid, button, day, count in buttons:
        button_stats[button]["presses"] += int(count or 0)
        button_stats[button]["people"].add(uid)

    order_rows = []
    for order in orders:
        source = by_id.get(order.user_id, (None, None, None))[2] or "no_source"
        order_rows.append({
            "id": order.id,
            "source": sources.НАЗВАНИЯ.get(source, source),
            "status": order.status,
            "created_at": _aware(order.created_at).isoformat() if order.created_at else None,
            "applied_at": _aware(order.applied_at).isoformat() if order.applied_at else None,
        })

    sources_rows = []
    for mark, data in sorted(by_source.items(), key=lambda item: -item[1]["starts"]):
        sources_rows.append({
            "mark": mark,
            "name": sources.НАЗВАНИЯ.get(mark, mark),
            **data,
        })

    return {
        "generated_at": now.isoformat(),
        "summary": {
            "profiles": len(by_id),
            "completed": len(completed),
            "incomplete": len(by_id) - len(completed),
            "completion_rate": round(len(completed) / len(by_id) * 100, 1) if by_id else 0,
            "new_last_7_days": sum(1 for _, (created, _, _) in by_id.items()
                                   if _aware(created) and _aware(created) >= week_ago),
            "orders": len(orders),
            "canceled_orders": sum(1 for order in orders if order.status == "CANCELED"),
            "paid_users": len(paid),
        },
        "by_source": sources_rows,
        "by_day": [
            {"day": str(day), **data}
            for day, data in sorted(by_day.items())[-14:]
        ],
        "incomplete_states": [
            {"state": state, "people": people}
            for state, people in incomplete_states.most_common()
        ],
        "events": [
            {"event": event, "count": data["count"], "people": len(data["people"])}
            for event, data in sorted(event_stats.items(),
                                      key=lambda item: -item[1]["count"])
        ],
        "nudge_kinds": dict(nudge_kinds),
        "buttons": [
            {"button": button, "presses": data["presses"],
             "people": len(data["people"])}
            for button, data in sorted(button_stats.items(),
                                       key=lambda item: -len(item[1]["people"]))[:30]
        ],
        "orders": order_rows[:20],
    }


async def main() -> None:
    try:
        print(json.dumps(await collect(), ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
