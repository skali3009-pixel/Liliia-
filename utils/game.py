"""Игровой слой: задания дня, опыт, уровни и награды — чистые функции.

Смысл в том, чтобы вся арифметика игры считалась по данным, которые уже есть
(еда, вода, тренировки, замеры), и ничего не приходилось отмечать руками.
Здесь только вычисления; запись в базу — в services/gamification.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Опыт за первый уровень и надбавка за каждый следующий: чем дальше, тем
# дороже уровень, иначе к третьему месяцу цифры перестают что-то значить.
BASE_LEVEL_XP = 100
LEVEL_XP_STEP = 50

# Норма калорий считается выполненной, если день закрыт в этом коридоре:
# недоедание — такой же промах, как перебор.
CALORIES_MIN_SHARE = 0.80
CALORIES_MAX_SHARE = 1.05

# Замер напоминаем раз в неделю — чаще нет смысла, вес скачет от воды.
MEASURE_EVERY_DAYS = 7

MEALS_TARGET = 3


@dataclass(frozen=True)
class Quest:
    """Одно задание дня с прогрессом «сколько из скольки»."""

    code: str
    title: str
    icon: str
    xp: int
    progress: float
    target: float
    done: bool
    hint: str

    @property
    def share(self) -> float:
        """Доля выполнения, 0..1 — для полоски прогресса."""
        if self.done:
            return 1.0
        if self.target <= 0:
            return 0.0
        return min(self.progress / self.target, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "icon": self.icon,
            "xp": self.xp,
            "done": self.done,
            "hint": self.hint,
            "share": round(self.share, 3),
        }


def _litres(ml: float) -> str:
    return f"{ml / 1000:.1f}".replace(".", ",")


def build_quests(
    *,
    meals_count: int,
    calories: float,
    calories_norm: float,
    water_ml: float,
    water_norm_ml: float,
    fiber_g: float,
    fiber_norm_g: float,
    workouts_today: int,
    days_since_measure: int | None,
    stress_marked: bool = False,
) -> list[Quest]:
    """Задания на сегодня, посчитанные по данным дня.

    Задание про замер появляется, только когда пора взвешиваться, — иначе
    список каждый день заканчивался бы невыполнимой строкой.
    """
    quests = [
        Quest(
            code="meals",
            title="Записать 3 приёма пищи",
            icon="🍽",
            xp=15,
            progress=meals_count,
            target=MEALS_TARGET,
            done=meals_count >= MEALS_TARGET,
            hint=f"{meals_count} из {MEALS_TARGET}",
        ),
        Quest(
            code="water",
            title="Выпить норму воды",
            icon="💧",
            xp=15,
            progress=water_ml,
            target=water_norm_ml,
            done=bool(water_norm_ml) and water_ml >= water_norm_ml,
            hint=f"{_litres(water_ml)} из {_litres(water_norm_ml)} л",
        ),
        Quest(
            code="calories",
            title="Уложиться в норму калорий",
            icon="🎯",
            xp=20,
            progress=calories,
            target=calories_norm,
            done=bool(calories_norm)
            and CALORIES_MIN_SHARE * calories_norm <= calories <= CALORIES_MAX_SHARE * calories_norm,
            hint=f"{round(calories)} из {round(calories_norm)} ккал",
        ),
        Quest(
            code="fiber",
            title="Набрать клетчатку",
            icon="🥦",
            xp=10,
            progress=fiber_g,
            target=fiber_norm_g,
            done=bool(fiber_norm_g) and fiber_g >= fiber_norm_g,
            hint=f"{round(fiber_g)} из {round(fiber_norm_g)} г",
        ),
        Quest(
            code="move",
            title="Позаниматься",
            icon="🏋️",
            xp=20,
            progress=workouts_today,
            target=1,
            done=workouts_today >= 1,
            hint="сделано" if workouts_today else "хотя бы одна тренировка",
        ),
        Quest(
            code="stress",
            title="Оценить уровень стресса",
            icon="〰️",
            xp=10,
            progress=1 if stress_marked else 0,
            target=1,
            done=stress_marked,
            # Стресс напрямую влияет на вес через кортизол и переедание —
            # это и есть повод отмечать его каждый день, а не только еду.
            hint="отмечено" if stress_marked else "он тоже влияет на вес",
        ),
    ]

    if days_since_measure is None or days_since_measure >= MEASURE_EVERY_DAYS:
        quests.append(
            Quest(
                code="measure",
                title="Записать замер",
                icon="📏",
                xp=15,
                progress=0,
                target=1,
                done=False,
                hint="пора взвеситься",
            )
        )

    return quests


def day_xp(quests: list[Quest]) -> int:
    """Опыт за выполненные сегодня задания."""
    return sum(quest.xp for quest in quests if quest.done)


def xp_for_level(level: int) -> int:
    """Сколько опыта нужно набрать внутри уровня, чтобы перейти на следующий."""
    return BASE_LEVEL_XP + LEVEL_XP_STEP * (max(level, 1) - 1)


@dataclass(frozen=True)
class Level:
    number: int
    xp_in_level: int
    xp_to_next: int

    @property
    def share(self) -> float:
        return self.xp_in_level / self.xp_to_next if self.xp_to_next else 0.0


def level_from_xp(total_xp: int) -> Level:
    """Уровень и прогресс внутри него по общему опыту."""
    level, left = 1, max(total_xp, 0)
    while left >= xp_for_level(level):
        left -= xp_for_level(level)
        level += 1
    return Level(number=level, xp_in_level=left, xp_to_next=xp_for_level(level))


# Кристалл растёт вместе с уровнем: пять ступеней, дальше только свечение.
CRYSTAL_STAGES = 5


def crystal_stage(level: int) -> int:
    """Ступень кристалла (1..5) для уровня."""
    return max(1, min(CRYSTAL_STAGES, (level + 3) // 4))


@dataclass(frozen=True)
class AchievementDef:
    code: str
    title: str
    icon: str
    goal: str


ACHIEVEMENTS: tuple[AchievementDef, ...] = (
    AchievementDef("first_step", "Первый шаг", "🌱", "первая запись еды"),
    AchievementDef("streak_7", "Неделя подряд", "🔥", "7 дней без пропусков"),
    AchievementDef("streak_30", "Месяц подряд", "🏆", "30 дней без пропусков"),
    AchievementDef("level_5", "Пятый уровень", "✨", "набрать 5-й уровень"),
    AchievementDef("minus_1kg", "Минус килограмм", "⚖️", "−1 кг от старта"),
    AchievementDef("minus_5kg", "Минус пять", "💎", "−5 кг от старта"),
    AchievementDef("waist_5cm", "Талия минус 5", "📏", "−5 см в талии"),
    AchievementDef("workouts_10", "Десять тренировок", "🏋️", "10 тренировок"),
    AchievementDef("workouts_50", "Полсотни", "🥇", "50 тренировок"),
)

ACHIEVEMENT_BY_CODE = {item.code: item for item in ACHIEVEMENTS}


def earned_codes(
    *,
    meals_total: int,
    streak: int,
    level: int,
    weight_lost_kg: float,
    waist_lost_cm: float,
    workouts_total: int,
) -> set[str]:
    """Какие награды заслужены прямо сейчас (уже выданные тоже попадают сюда)."""
    earned: set[str] = set()
    if meals_total >= 1:
        earned.add("first_step")
    if streak >= 7:
        earned.add("streak_7")
    if streak >= 30:
        earned.add("streak_30")
    if level >= 5:
        earned.add("level_5")
    if weight_lost_kg >= 1:
        earned.add("minus_1kg")
    if weight_lost_kg >= 5:
        earned.add("minus_5kg")
    if waist_lost_cm >= 5:
        earned.add("waist_5cm")
    if workouts_total >= 10:
        earned.add("workouts_10")
    if workouts_total >= 50:
        earned.add("workouts_50")
    return earned
