import asyncio
from urllib.parse import urlsplit, parse_qs
from unittest.mock import AsyncMock

import config
import scheduler
from handlers.workouts import _open_app_keyboard


def test_trial_notifications_disabled_with_paywall(monkeypatch):
    monkeypatch.setattr(config, 'PAYWALL', False)
    def forbidden():
        raise AssertionError('Disabled paywall must not inspect or expire subscriptions')
    monkeypatch.setattr(scheduler, 'get_session', forbidden)
    bot = AsyncMock()
    asyncio.run(scheduler.check_subscriptions(bot))
    bot.send_message.assert_not_called()


def test_workout_link_preserves_query_and_targets_gym(monkeypatch):
    monkeypatch.setattr(config, 'WEBAPP_URL', 'https://example.org/app?from=chat#anchor')
    url = _open_app_keyboard().inline_keyboard[0][0].web_app.url
    assert parse_qs(urlsplit(url).query) == {'from': ['chat'], 'screen': ['gym']}
    assert urlsplit(url).fragment == 'anchor'
