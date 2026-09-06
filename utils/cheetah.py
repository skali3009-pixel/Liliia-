"""Гепард: настроение приложения, а не второй советчик.

Разделение простое. Думает AURA — она считает, что человеку сейчас полезно,
и говорит это в карточке «Твой ход». Гепард ничего не советует: он реагирует.
Утром потягивается, вечером зевает, после тренировки доволен, после долгого
перерыва встречает — и ни при каких обстоятельствах не упрекает.

Состояние выбирается по тем же данным, что и подсказки: час, силы, стресс,
вода, тренировки, серия. Никакой отдельной модели и никаких запросов к сети:
это чистая функция от того, что уже посчитано.
"""

from __future__ import annotations

from dataclasses import dataclass

# Порядок важен: первое подошедшее и побеждает. Сверху — редкие и радостные
# события, снизу — обычное течение дня.
IDLE = "idle"
MORNING = "morning"
EVENING = "evening"
SLEEPY = "sleepy"
ENERGETIC = "energetic"
THIRSTY = "thirsty"
ACTIVE = "active"
PROUD = "proud"
CELEBRATION = "celebration"
RETURNING = "returning"
STREAK = "streak"
WORLD_UNLOCK = "world_unlock"


@dataclass(frozen=True)
class Mood:
    """Что с гепардом сейчас."""

    code: str
    emoji: str
    line: str

    def to_dict(self) -> dict:
        return {"code": self.code, "emoji": self.emoji, "line": self.line}


def mood(*, hour: int, energy: int | None = None, stress: str | None = None,
         water_share: float = 1.0, workouts_today: int = 0, streak: int = 0,
         days_away: int = 0, new_awards: int = 0, world_unlock: bool = False,
         quests_done: int = 0, quests_total: int = 0) -> Mood:
    """Настроение гепарда по состоянию дня.

    `water_share` — какая доля нормы воды набрана, 0..1.
    `days_away` — сколько дней человек не заходил.
    """
    if world_unlock:
        return Mood(WORLD_UNLOCK, "✨",
                    "В твоём мире стало на одно место больше. Он это заметил.")

    if new_awards:
        return Mood(CELEBRATION, "🎉",
                    "Гепард носится кругами. Ты открыла новое.")

    # Возвращение — самое важное из всего: именно здесь человека легче всего
    # потерять окончательно. Ни слова про пропуски.
    if days_away >= 3:
        return Mood(RETURNING, "🐆",
                    "Мир тебя дождался. Продолжаем с того же места.")

    if streak >= 7 and quests_done:
        return Mood(STREAK, "🔥",
                    f"{streak} дней подряд. Гепард уже привык, что ты приходишь.")

    if quests_total and quests_done >= quests_total:
        return Mood(PROUD, "😌",
                    "Всё на сегодня закрыто. Можно выдохнуть.")

    if workouts_today:
        return Mood(ACTIVE, "💪",
                    "После тренировки он такой же довольный, как ты.")

    tired = (energy is not None and energy <= 2) or stress == "high"
    if tired or hour >= 22 or hour < 6:
        return Mood(SLEEPY, "😴",
                    "Гепард свернулся клубком. Сегодня можно потише.")

    if water_share < 0.35 and 10 <= hour < 21:
        return Mood(THIRSTY, "💧",
                    "Он поглядывает на воду. Намекает.")

    if energy is not None and energy >= 4:
        return Mood(ENERGETIC, "⚡",
                    "Сил много — у него тоже. Хороший день, чтобы двигаться.")

    if 6 <= hour < 11:
        return Mood(MORNING, "🌅", "Потягивается. День только начинается.")

    if 18 <= hour < 22:
        return Mood(EVENING, "🌙", "Вечер. Он уже никуда не бежит.")

    return Mood(IDLE, "🐆", "Лежит рядом и наблюдает.")


__all__ = ["ACTIVE", "CELEBRATION", "ENERGETIC", "EVENING", "IDLE", "MORNING",
           "Mood", "PROUD", "RETURNING", "SLEEPY", "STREAK", "THIRSTY",
           "WORLD_UNLOCK", "mood"]
