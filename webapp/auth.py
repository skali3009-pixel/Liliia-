"""Проверка подписи Telegram Mini App.

Открывая приложение, Telegram передаёт строку initData с данными
пользователя и подписью. Подпись доказывает, что данные пришли от Telegram
и не подделаны — без этой проверки любой человек мог бы открыть чужой
дневник, просто подставив чужой id.

Алгоритм (документация Telegram Mini Apps):
    secret = HMAC_SHA256(key="WebAppData", msg=<токен бота>)
    hash   = HMAC_SHA256(key=secret, msg=<данные, отсортированные по ключу>)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

# Данные старше суток не принимаем: страховка от повторного использования
# перехваченной ссылки.
MAX_AGE_SECONDS = 24 * 60 * 60


class AuthError(Exception):
    """initData отсутствует, подделана или просрочена."""


@dataclass(frozen=True)
class WebAppUser:
    id: int
    first_name: str
    username: str | None
    language_code: str | None


def _data_check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")


def verify_init_data(init_data: str, bot_token: str, *, now: float | None = None) -> WebAppUser:
    """Проверить подпись и вернуть пользователя. Иначе — AuthError."""
    if not init_data:
        raise AuthError("Нет данных авторизации")

    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.get("hash")
    if not received_hash:
        raise AuthError("В данных нет подписи")

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, _data_check_string(fields).encode(), hashlib.sha256
    ).hexdigest()

    # Сравнение, устойчивое к атаке по времени ответа.
    if not hmac.compare_digest(expected_hash, received_hash):
        raise AuthError("Подпись не совпала")

    auth_date = fields.get("auth_date", "")
    if not auth_date.isdigit():
        raise AuthError("Нет времени авторизации")
    age = (now if now is not None else time.time()) - int(auth_date)
    if age > MAX_AGE_SECONDS:
        raise AuthError("Данные авторизации устарели — переоткрой приложение")
    if age < -300:  # часы сервера ушли вперёд больше чем на 5 минут
        raise AuthError("Некорректное время авторизации")

    try:
        raw_user = json.loads(fields.get("user", "{}"))
        user_id = int(raw_user["id"])
    except (ValueError, KeyError, TypeError) as e:
        raise AuthError("В данных нет пользователя") from e

    return WebAppUser(
        id=user_id,
        first_name=str(raw_user.get("first_name", "")),
        username=raw_user.get("username"),
        language_code=raw_user.get("language_code"),
    )
