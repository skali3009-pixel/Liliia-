"""Сбор данных Instagram (профиль, метрики, посты) через Composio API.

Composio должен быть настроен заранее: аккаунт на app.composio.dev,
API-ключ в .env (COMPOSIO_API_KEY), и Instagram Business/Creator-аккаунт,
подключённый через app.composio.dev -> Connected Accounts -> Instagram
(подробности в README.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from composio_client import Composio

import config

_client: Composio | None = None

# Метрики аккаунта, которые Instagram отдаёт только как накопленную сумму
# за период (metric_type=total_value) — так работает Instagram Graph API.
ACCOUNT_TOTAL_METRICS = [
    "accounts_engaged", "total_interactions", "likes", "comments",
    "shares", "saves", "profile_views",
]
# А эти — как ряд по дням (metric_type=time_series), их суммируем сами.
ACCOUNT_TIME_SERIES_METRICS = ["reach", "follower_count"]

MEDIA_METRICS = ["views", "reach", "likes", "comments", "saved", "shares", "total_interactions"]


class InstagramNotConnected(Exception):
    """Нет активного подключения Instagram в Composio."""


def _get_client() -> Composio:
    global _client
    if _client is None:
        _client = Composio(api_key=config.COMPOSIO_API_KEY)
    return _client


def _get_connected_account_id() -> str:
    result = _get_client().connected_accounts.list(
        toolkit_slugs=["instagram"], statuses=["ACTIVE"], limit=1,
    )
    if not result.items:
        raise InstagramNotConnected(
            "Нет активного подключения Instagram в Composio.\n\n"
            "Подключите Business/Creator-аккаунт на "
            "https://app.composio.dev в разделе Connected Accounts -> Instagram, "
            "и повторите команду /audit."
        )
    return result.items[0].id


def _execute(tool_slug: str, arguments: dict, connected_account_id: str) -> dict:
    response = _get_client().tools.execute(
        tool_slug, arguments=arguments, connected_account_id=connected_account_id,
    )
    if not response.successful:
        raise RuntimeError(f"{tool_slug} завершился с ошибкой: {response.error}")
    return response.data or {}


def fetch_snapshot(recent_media_limit: int = 12) -> dict:
    """Собирает профиль, метрики аккаунта за 30 дней и данные последних постов.

    Данные реальные, напрямую из Instagram Graph API (через Composio) —
    без каких-либо предположений или подмены значений.
    """
    account_id = _get_connected_account_id()

    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    until = now.strftime("%Y-%m-%d")

    profile = _execute("INSTAGRAM_GET_USER_INFO", {"ig_user_id": "me"}, account_id)

    time_series = _execute("INSTAGRAM_GET_USER_INSIGHTS", {
        "ig_user_id": "me", "metric": ACCOUNT_TIME_SERIES_METRICS, "period": "day",
        "since": since, "until": until, "metric_type": "time_series",
    }, account_id)
    totals = _execute("INSTAGRAM_GET_USER_INSIGHTS", {
        "ig_user_id": "me", "metric": ACCOUNT_TOTAL_METRICS, "period": "day",
        "since": since, "until": until, "metric_type": "total_value",
    }, account_id)

    account_metrics = {"reach_30d": 0, "follower_change_30d": 0}
    for m in time_series.get("data") or []:
        values = [v.get("value", 0) or 0 for v in (m.get("values") or [])]
        if m.get("name") == "reach":
            account_metrics["reach_30d"] = sum(values)
        elif m.get("name") == "follower_count":
            account_metrics["follower_change_30d"] = sum(values)
    for m in totals.get("data") or []:
        name = m.get("name")
        if name:
            account_metrics[name] = (m.get("total_value") or {}).get("value", 0)

    media_resp = _execute(
        "INSTAGRAM_GET_IG_USER_MEDIA", {"ig_user_id": "me", "limit": recent_media_limit}, account_id,
    )
    media_items = media_resp.get("data") or []

    posts = []
    for item in media_items:
        metrics_to_ask = list(MEDIA_METRICS)
        # Карусели не поддерживают метрику "shares" — иначе запрос упадёт.
        if item.get("media_type") == "CAROUSEL_ALBUM":
            metrics_to_ask.remove("shares")
        try:
            insights = _execute(
                "INSTAGRAM_GET_IG_MEDIA_INSIGHTS",
                {"ig_media_id": item["id"], "metric": metrics_to_ask},
                account_id,
            )
            post_metrics = {
                m.get("name"): (m.get("values") or [{}])[0].get("value", 0)
                for m in (insights.get("data") or [])
            }
        except Exception:
            # Метрики недоступны (например, слишком старый пост) — не критично.
            post_metrics = {}
        posts.append({
            "id": item.get("id"),
            "caption": (item.get("caption") or "")[:300],
            "media_type": item.get("media_type"),
            "permalink": item.get("permalink"),
            "timestamp": item.get("timestamp"),
            "is_shared_to_feed": item.get("is_shared_to_feed", True),
            "metrics": post_metrics,
        })

    return {
        "profile": {
            "username": profile.get("username"),
            "name": profile.get("name"),
            "biography": profile.get("biography"),
            "website": profile.get("website"),
            "followers_count": profile.get("followers_count") or 0,
            "follows_count": profile.get("follows_count") or 0,
            "media_count": profile.get("media_count") or 0,
            "account_type": profile.get("account_type"),
        },
        "period": {"since": since, "until": until},
        "account_metrics": account_metrics,
        "posts": posts,
    }
