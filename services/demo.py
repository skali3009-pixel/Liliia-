"""Одна бесплатная примерка еды до оплаты.

Идея простая: человек уже заполнил анкету и получил норму, но ещё не видел,
как бот считает еду. Один разбор — это настоящая польза, а не обещание:
после него понятно, как работает главная функция, сколько это стоит по
времени и насколько результат похож на правду.

Правила:

- только для новых пользователей, начавших анкету после ``SINCE``: старая
  когорта уже получила свою воронку, и смешивать её с новым экспериментом
  нельзя;
- только до оплаты и только один успешный разбор на аккаунт;
- окно — те же три дня, что и у промо-серии, с техническим запасом;
- ошибка распознавания попытку не тратит: человек может прислать другое фото
  или описать еду словами.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models import User
from services import age as age_rules
from services.subscriptions import _aware

# Демо появляется у тех, кто завершил анкету после этого момента. Значение
# зафиксировано на выпуске: у старой когорты promo_started_at стоит раньше.
SINCE = datetime(2026, 11, 8, 13, 45, tzinfo=timezone.utc)

# Столько же, сколько действует промо-цена: если скидка кончилась, примерка
# тоже больше не предлагается.
WINDOW = timedelta(days=3, hours=2)


def available(user: User | None, *, allowed: bool,
              now_utc: datetime | None = None) -> bool:
    """Можно ли предложить этому человеку бесплатный разбор."""
    if allowed or user is None or not user.onboarding_completed:
        return False
    if age_rules.is_minor(user):
        return False
    if user.demo_food_at is not None:
        return False
    started = _aware(user.promo_started_at)
    if started is None or started < SINCE:
        return False
    moment = now_utc or datetime.now(timezone.utc)
    return moment < started + WINDOW


def message_allowed(user: User | None, state: str, *, allowed: bool,
                    now_utc: datetime | None = None) -> bool:
    """Пускает сообщения только внутри состояния примерки."""
    return (state or "").startswith("DemoStates:") and available(
        user, allowed=allowed, now_utc=now_utc)
