"""Срочные сигналы владельцу: то, от чего зависит что-то прямо сейчас.

Главная опасность здесь — не пропустить событие, а утопить владельца в
повторах. Сигнал, который приходит каждые десять минут, через день
перестают читать, и тогда теряется тот единственный, который был важен.
Поэтому:

- сигнал уходит один раз на событие и молчит, пока состояние не изменится;
- когда отпустило — приходит короткое «всё в порядке», чтобы не гадать;
- общий ограничитель: не больше нескольких сообщений в час, что бы ни
  случилось.

Состояние держим в памяти процесса. Перезапуск бота его сбрасывает — тогда
владелец в худшем случае получит один повтор, и это лучше, чем таблица в
базе ради шести переменных.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta, timezone

from aiogram import Bot

import config

logger = logging.getLogger(__name__)

# Ключи сигналов: по одному на вид события.
DISK = "disk"
BUDGET = "budget"
SPIKE = "spend_spike"
ERRORS = "errors"

# Не больше стольких сообщений владельцу в час — на все виды сигналов вместе.
MAX_PER_HOUR = 6

# Сколько ошибок подряд за сколько минут считаем поломкой, а не невезением.
ERROR_THRESHOLD = 5
ERROR_WINDOW = timedelta(minutes=10)

# Текущее состояние каждого сигнала: пусто — всё спокойно.
_state: dict[str, str] = {}
# Время последних отправок — для ограничителя частоты.
_sent: deque[datetime] = deque(maxlen=MAX_PER_HOUR * 4)
# Отметки об ошибках модели.
_failures: deque[datetime] = deque(maxlen=200)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def reset() -> None:
    """Забыть всё — нужно тестам и при перенастройке."""
    _state.clear()
    _sent.clear()
    _failures.clear()


def _allowed(moment: datetime) -> bool:
    """Не превышен ли часовой лимит сообщений."""
    edge = moment - timedelta(hours=1)
    while _sent and _sent[0] < edge:
        _sent.popleft()
    return len(_sent) < MAX_PER_HOUR


async def send(bot: Bot, text: str) -> bool:
    """Сообщение владельцу под общим часовым ограничителем.

    Публичная: под тем же лимитом должны ходить и сигналы сторожа, и
    сообщения о поломках — иначе один шумный источник съедает внимание,
    которого хватило бы на важное.
    """
    moment = _now()
    if not _allowed(moment):
        logger.warning("Сигнал придержан — превышен лимит сообщений в час: %s", text[:60])
        return False

    delivered = False
    for admin in config.ADMIN_IDS:
        try:
            await bot.send_message(admin, text)
            delivered = True
        except Exception:  # noqa: BLE001 — владелец мог заблокировать бота
            logger.warning("Не удалось отправить сигнал владельцу %s", admin)
    if delivered:
        _sent.append(moment)
    return delivered


async def fire(bot: Bot, key: str, state: str, text: str) -> bool:
    """Сообщить о событии, если его состояние изменилось.

    `state` — короткое описание того, что сейчас («90», «over»). Пока оно
    не меняется, повторов не будет.
    """
    if not config.ADMIN_IDS or _state.get(key) == state:
        return False
    _state[key] = state
    return await send(bot, text)


async def resolve(bot: Bot, key: str, text: str) -> bool:
    """Сообщить, что отпустило, — но только если раньше был сигнал."""
    if not config.ADMIN_IDS or not _state.get(key):
        return False
    _state.pop(key, None)
    return await send(bot, text)


def record_failure() -> bool:
    """Отметить сбой при обращении к модели.

    Возвращает True, когда сбоев за окно накопилось столько, что это уже
    поломка: бот жив, а людям не отвечает — сторож такое не ловит.
    """
    moment = _now()
    _failures.append(moment)
    edge = moment - ERROR_WINDOW
    while _failures and _failures[0] < edge:
        _failures.popleft()
    return len(_failures) >= ERROR_THRESHOLD


def failures_in_window() -> int:
    return len(_failures)


__all__ = ["BUDGET", "DISK", "ERRORS", "ERROR_THRESHOLD", "ERROR_WINDOW",
           "send",
           "MAX_PER_HOUR", "SPIKE", "failures_in_window", "fire", "record_failure",
           "reset", "resolve"]
