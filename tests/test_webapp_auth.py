"""Тесты проверки подписи Telegram Mini App — это защита чужих данных."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from webapp.auth import MAX_AGE_SECONDS, AuthError, verify_init_data

BOT_TOKEN = "8123456789:AAFakeTokenForTestsOnly-000000000000000"
USER = {"id": 4242, "first_name": "Лилия", "username": "liliia", "language_code": "ru"}


def make_init_data(*, token=BOT_TOKEN, user=None, auth_date=None, tamper=False) -> str:
    fields = {
        "user": json.dumps(user or USER, ensure_ascii=False, separators=(",", ":")),
        "auth_date": str(int(auth_date if auth_date is not None else time.time())),
        "query_id": "AAF123",
    }
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if tamper:
        # Подменяем пользователя уже после подписи — так поступил бы злоумышленник.
        fields["user"] = json.dumps({**USER, "id": 9999}, ensure_ascii=False, separators=(",", ":"))
    return urlencode(fields)


def test_valid_init_data_returns_user():
    user = verify_init_data(make_init_data(), BOT_TOKEN)
    assert user.id == 4242
    assert user.first_name == "Лилия"
    assert user.username == "liliia"


def test_tampered_user_is_rejected():
    """Главный сценарий: подмена чужого id должна ломать подпись."""
    with pytest.raises(AuthError, match="Подпись не совпала"):
        verify_init_data(make_init_data(tamper=True), BOT_TOKEN)


def test_signature_from_another_bot_is_rejected():
    other = make_init_data(token="9999999999:AAAnotherBotTokenXXXXXXXXXXXXXXXXXXX")
    with pytest.raises(AuthError, match="Подпись не совпала"):
        verify_init_data(other, BOT_TOKEN)


def test_expired_init_data_is_rejected():
    old = make_init_data(auth_date=time.time() - MAX_AGE_SECONDS - 60)
    with pytest.raises(AuthError, match="устарели"):
        verify_init_data(old, BOT_TOKEN)


def test_fresh_init_data_within_window_is_accepted():
    recent = make_init_data(auth_date=time.time() - MAX_AGE_SECONDS + 60)
    assert verify_init_data(recent, BOT_TOKEN).id == 4242


@pytest.mark.parametrize("bad", ["", "user=%7B%7D", "hash=abc&auth_date=123"])
def test_broken_init_data_is_rejected(bad):
    with pytest.raises(AuthError):
        verify_init_data(bad, BOT_TOKEN)


def test_init_data_without_user_is_rejected():
    fields = {"auth_date": str(int(time.time())), "query_id": "AAF"}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(AuthError, match="нет пользователя"):
        verify_init_data(urlencode(fields), BOT_TOKEN)
