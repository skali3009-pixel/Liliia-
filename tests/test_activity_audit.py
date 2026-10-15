from datetime import date, datetime, timezone
from types import SimpleNamespace as Row
import json

from services.activity_audit import build_report

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def user(uid, complete=False, app=None, bot=None):
    return Row(id=uid, created_at=NOW, onboarding_completed=complete,
               last_app_open=app, last_bot_action=bot)


def test_distinct_days_not_event_counts_and_excludes_admin_from_summary():
    events = [Row(user_id=12, day=date(2026, 10, 14), event='active_day'),
              Row(user_id=12, day=date(2026, 10, 14), event='action_completed'),
              Row(user_id=12, day=date(2026, 10, 12), event='action_completed'),
              Row(user_id=99, day=date(2026, 10, 15), event='active_day')]
    result = build_report([user(12, True), user(99, True), user(33)], events, [],
                          now=NOW, admins={99}, secret='test')
    row = result['profiles'][0]
    assert row['observed_useful_days'] == 2
    assert row['useful_span_days'] == 3
    assert row['days_since_observed'] == 1
    assert result['summary']['useful_last_14_days_non_admin'] == 1
    assert result['summary']['non_admin_profiles'] == 2
    assert result['profiles'][2]['last_observed_day'] is None
    assert result['profiles'][2]['days_since_observed'] is None
    assert 'user_id' not in json.dumps(result)


def test_presence_does_not_fabricate_historical_active_days_or_usefulness():
    # SQLite timestamps can be naive UTC. 22:00 UTC is next day in Moscow.
    result = build_report([user(12, True, bot=datetime(2026, 10, 14, 22))], [],
                          [Row(user_id=12, day=date(2026, 10, 10))],
                          now=NOW, admins=set(), secret='test')
    row = result['profiles'][0]
    assert row['last_observed_day'] == '2026-10-15'
    assert row['observed_useful_days'] == 0
    assert row['observed_event_or_menu_days'] == 1
    assert row['stage'] == 'profile_complete_no_useful_action_observed'


def test_pseudonyms_are_stable_keyed_and_future_events_ignored():
    kwargs = dict(users=[user(12)], events=[Row(user_id=12, day=date(2027, 1, 1), event='active_day')],
                  buttons=[], now=NOW, admins=set(), secret='one')
    first = build_report(**kwargs)['profiles'][0]
    assert first['profile'] == build_report(**kwargs)['profiles'][0]['profile']
    kwargs['secret'] = 'two'
    assert first['profile'] != build_report(**kwargs)['profiles'][0]['profile']
    assert first['observed_useful_days'] == 0


def test_collect_selects_allowlisted_columns_without_writes(monkeypatch):
    import asyncio
    from sqlalchemy import event
    from services import activity_audit
    from tests.test_webapp_api import webapp_client, maker_holder

    async def scenario():
        async with webapp_client():
            maker = maker_holder['maker']
            monkeypatch.setattr(activity_audit, 'async_session_maker', maker)
            statements = []
            bind = maker.kw['bind']
            def record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)
            event.listen(bind.sync_engine, 'before_cursor_execute', record)
            try:
                report = await activity_audit.collect()
                assert report['summary']['profiles'] >= 2
                assert len(statements) == 3
                assert all(s.lstrip().upper().startswith('SELECT') for s in statements)
                assert not any('full_name' in s or 'allergies' in s or 'weight' in s for s in statements)
            finally:
                event.remove(bind.sync_engine, 'before_cursor_execute', record)
    asyncio.run(scenario())
