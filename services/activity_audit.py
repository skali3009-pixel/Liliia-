"""Read-only, pseudonymous activity export. No messages, inference or writes."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

import config
from db import async_session_maker, engine
from models import User, MarketingEvent, ButtonPress
from services.analytics import STARTED_ON

TZ = ZoneInfo('Europe/Moscow')


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def build_report(users, events, buttons, *, now, admins, secret):
    """Inputs contain only the allowlisted columns selected below."""
    today = now.astimezone(TZ).date()
    by_user = defaultdict(list)
    clicks = defaultdict(set)
    for event in events:
        if event.day <= today:
            by_user[event.user_id].append(event)
    for click in buttons:
        if click.day <= today:
            clicks[click.user_id].add(click.day)
    rows = []
    for user in users:
        observed = by_user[user.id]
        useful_days = {e.day for e in observed if e.event == 'active_day'}
        action_days = {e.day for e in observed if e.event == 'action_completed'}
        useful_days |= action_days
        event_days = {e.day for e in observed} | clicks[user.id]
        touches = [aware(t) for t in (user.last_app_open, user.last_bot_action) if t]
        last_touch = max(touches) if touches else None
        all_days = event_days | {t.astimezone(TZ).date() for t in touches}
        last_day = max(all_days) if all_days else None
        has_action = bool(useful_days)
        stage = ('useful_action_observed' if has_action else
                 'profile_complete_no_useful_action_observed' if user.onboarding_completed else
                 'profile_incomplete')
        rows.append({
            'profile': 'U-' + hmac.new(secret.encode(), f'activity:{user.id}'.encode(), hashlib.sha256).hexdigest()[:12],
            'configured_admin': user.id in admins,
            'created_at': aware(user.created_at).isoformat(),
            'onboarding_completed': user.onboarding_completed,
            'last_app_request_at': aware(user.last_app_open).isoformat() if user.last_app_open else None,
            'last_bot_action_at': aware(user.last_bot_action).isoformat() if user.last_bot_action else None,
            'last_presence_at': last_touch.isoformat() if last_touch else None,
            'last_observed_day': str(last_day) if last_day else None,
            'days_since_observed': (today-last_day).days if last_day else None,
            'observed_useful_days': len(useful_days),
            'observed_event_or_menu_days': len(event_days),
            'first_useful_day': str(min(useful_days)) if useful_days else None,
            'last_useful_day': str(max(useful_days)) if useful_days else None,
            'useful_span_days': (max(useful_days)-min(useful_days)).days+1 if useful_days else 0,
            'useful_days_last_14': len({d for d in useful_days if d >= today-timedelta(days=13)}),
            'stage': stage,
        })
    people = [r for r in rows if not r['configured_admin']]
    return {'generated_at': now.isoformat(), 'timezone': str(TZ),
            'analytics_started_on': str(STARTED_ON),
            'limitations': ['Presence is not a complete visit history; bot timestamps are throttled to five minutes.',
                           'Useful-day coverage is limited to instrumented actions; zero means none observed.',
                           'Other test accounts are not automatically identifiable.',
                           'Stages describe observed state, not causes of churn or exact questionnaire steps.',
                           'Pseudonyms change if the bot token is rotated.'],
            'summary': {'profiles': len(rows), 'configured_admins': len(rows)-len(people),
                        'non_admin_profiles': len(people),
                        'stages_non_admin': dict(Counter(r['stage'] for r in people)),
                        'observed_last_7_days_non_admin': sum(r['days_since_observed'] is not None and 0 <= r['days_since_observed'] < 7 for r in people),
                        'useful_last_14_days_non_admin': sum(r['useful_days_last_14'] > 0 for r in people)},
            'profiles': rows}


async def collect():
    async with async_session_maker() as session:
        # A single consistent snapshot; PostgreSQL rejects accidental writes.
        if session.bind.dialect.name == 'postgresql':
            await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        users = (await session.execute(select(User.id, User.created_at, User.onboarding_completed,
                                             User.last_app_open, User.last_bot_action).order_by(User.created_at, User.id))).all()
        events = (await session.execute(select(MarketingEvent.user_id, MarketingEvent.event, MarketingEvent.day))).all()
        buttons = (await session.execute(select(ButtonPress.user_id, ButtonPress.day))).all()
        return build_report(users, events, buttons, now=datetime.now(timezone.utc),
                            admins=config.ADMIN_IDS, secret=config.BOT_TOKEN)


async def main():
    try:
        print(json.dumps(await collect(), ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
