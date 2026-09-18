"""«Что-то не так»: голос человека доходит до владельца, а ответ — обратно.

Поломки бот теперь ловит сам. Но самое частое — не поломка. «Пришёл какой-то
отчёт, что это?», «непонятно, куда нажимать», «посчитало вдвое больше, чем
я съела» — всё это работает как задумано и в логах выглядит безупречно.
Узнать об этом можно только от человека, а человек напишет, только если ему
есть куда.

Поэтому здесь два направления сразу. Без обратного письмо превращается в
ящик для жалоб: у многих в Telegram нет имени пользователя, и ответить им
владелец не сможет никак, даже зная номер.

Ограничитель — не про вежливость, а про то, чтобы кнопкой нельзя было
завалить чат владельца: несколько сообщений в час от одного человека.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot

import config

logger = logging.getLogger(__name__)

# Длиннее этого в чат не уедет: рассказ должен помещаться в сообщение.
MAX_TEXT = 1000

# Сколько сообщений от одного человека принимаем за час.
PER_HOUR = 3
WINDOW = timedelta(hours=1)

# Кто когда писал. В памяти процесса: перезапуск сбрасывает счётчик, и это
# не беда — ограничитель защищает от потока, а не от третьего сообщения.
_sent: dict[int, deque[datetime]] = {}


def reset() -> None:
    """Забыть счётчики. Нужно тестам."""
    _sent.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clean(text: str) -> str:
    """Что из присланного вообще можно передавать дальше."""
    return " ".join(str(text or "").split())[:MAX_TEXT]


def allowed(user_id: int) -> bool:
    """Не слишком ли часто пишет этот человек."""
    moment = _now()
    marks = _sent.setdefault(user_id, deque(maxlen=PER_HOUR * 4))
    while marks and marks[0] < moment - WINDOW:
        marks.popleft()
    if len(marks) >= PER_HOUR:
        return False
    marks.append(moment)
    return True


@dataclass(frozen=True)
class Report:
    """Что человек рассказал и откуда."""

    user_id: int
    name: str
    where: str
    text: str


def render(report: Report) -> str:
    """Сообщение владельцу. Сразу видно, кто написал и о чём."""
    who = report.name.strip() or "без имени"
    return "\n".join([
        "✍️ Человек пишет, что что-то не так",
        "",
        f"Кто: {who} ({report.user_id})",
        f"Откуда: {report.where}",
        "",
        report.text,
    ])


ANSWER_PREFIX = "✉️ Ответ от хозяйки бота:"


async def deliver(bot: Bot, report: Report, *, keyboard=None) -> bool:
    """Передать рассказ владельцу. Возвращает False, если некому."""
    if not config.ADMIN_IDS:
        logger.info("Некому передать сообщение от %s: владелец не задан",
                    report.user_id)
        return False

    delivered = False
    for admin in config.ADMIN_IDS:
        try:
            await bot.send_message(admin, render(report), reply_markup=keyboard)
            delivered = True
        except Exception:  # noqa: BLE001 — владелец мог заблокировать бота
            logger.warning("Не удалось передать сообщение владельцу %s", admin)
    return delivered


async def answer(bot: Bot, user_id: int, text: str) -> bool:
    """Ответ владельца — человеку. Подписан, чтобы не выглядел рассылкой."""
    body = clean(text)
    if not body:
        return False
    try:
        await bot.send_message(user_id, f"{ANSWER_PREFIX}\n\n{body}")
        return True
    except Exception:  # noqa: BLE001 — человек мог заблокировать бота
        logger.warning("Не удалось доставить ответ человеку %s", user_id)
        return False


__all__ = ["ANSWER_PREFIX", "MAX_TEXT", "PER_HOUR", "Report", "allowed", "answer",
           "clean", "deliver", "render", "reset"]
