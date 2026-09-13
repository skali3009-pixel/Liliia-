"""Маленькие события мира и редкие находки.

Задумано просто: иногда в мире что-то происходит, и это приятно. Но именно
такие механики легче всего испортить, поэтому границы записаны явно.

Чего здесь нет и не будет:
- ставок и «покрутить»: человек ничего не запускает и ничем не рискует;
- потерь: событие можно не выполнить, но отнять за это нельзя ничего;
- переменного выигрыша: награда фиксированная и известна заранее;
- награды за вредное: и событие, и находка привязаны к обычным заданиям
  дня, а те уже устроены так, что за голодание и перегрузку не платят.

И главное: событие выбирается детерминированно — по человеку и дате. Одно и
то же обновление экрана не может выдать другое событие, а значит «крутить»
нечего. Это не украшение формулировки, это и есть защита от азартности.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# Сколько кристаллов даёт событие и находка. Для сравнения: идеальный день —
# 105. Бонус должен быть приятным, а не важнее самого дня.
EVENT_CRYSTALS = 15
SURPRISE_CRYSTALS = 5

# В какой доле дней вообще что-то происходит. Событие каждый день перестаёт
# быть событием.
EVENT_CHANCE = 0.4
SURPRISE_CHANCE = 0.2

# Сколько заданий надо закрыть, чтобы событие случилось.
EVENT_TARGET = 2


@dataclass(frozen=True)
class Event:
    """Событие дня: что происходит и что для этого сделать."""

    code: str
    icon: str
    title: str
    text: str
    target: int = EVENT_TARGET
    crystals: int = EVENT_CRYSTALS

    def to_dict(self) -> dict:
        return {"code": self.code, "icon": self.icon, "title": self.title,
                "text": self.text, "target": self.target,
                "crystals": self.crystals}


EVENTS: tuple[Event, ...] = (
    Event("chest", "🎁", "Гепард нашёл сундук",
          "Он его не откроет — лапами неудобно. Закрой любые два задания, "
          "и посмотрим, что внутри."),
    Event("rare_day", "✨", "Редкий день",
          "Сегодня в мире что-то звенит. Два закрытых задания — и звон "
          "станет кристаллами."),
    Event("visitor", "🐾", "Кто-то приходил",
          "У воды свежие следы. Закрой два задания, и гепард выяснит, чьи."),
    Event("wind", "🍃", "Тёплый ветер",
          "Хороший день, чтобы что-нибудь закрыть. Два задания — и ветер "
          "принесёт кристаллы."),
)


def _dice(*parts: object) -> float:
    """Случайность, привязанная к человеку и дню, а не к моменту запроса.

    Обновление экрана не должно менять исход — иначе появляется смысл
    «крутить», а это ровно то, чего здесь быть не должно.
    """
    raw = ":".join(str(part) for part in parts).encode()
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def event_for(user_id: int, day: str) -> Event | None:
    """Событие этого дня у этого человека — или ничего."""
    if _dice("event", user_id, day) >= EVENT_CHANCE:
        return None
    index = int(_dice("which", user_id, day) * len(EVENTS))
    return EVENTS[min(index, len(EVENTS) - 1)]


def surprise_for(user_id: int, day: str) -> int:
    """Сколько кристаллов принесёт находка этого дня. Ноль — если её нет.

    Находка не выдаётся сама по себе: она случается только после того, как
    человек закрыл задание. Здесь решается лишь, случится ли она вообще.
    """
    return SURPRISE_CRYSTALS if _dice("surprise", user_id, day) < SURPRISE_CHANCE else 0


__all__ = ["EVENTS", "EVENT_CHANCE", "EVENT_CRYSTALS", "EVENT_TARGET", "Event",
           "SURPRISE_CHANCE", "SURPRISE_CRYSTALS", "event_for", "surprise_for"]
