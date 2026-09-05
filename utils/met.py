"""Расход калорий на тренировке по MET-формуле.

MET (metabolic equivalent of task) — во сколько раз упражнение энергозатратнее
покоя. Стандартная формула:

    ккал = MET × вес(кг) × время(ч)

Значения MET взяты из Compendium of Physical Activities — общепринятого
справочника: спокойная ходьба ~3, бег трусцой ~7, силовая работа 3.5–6.
"""

from __future__ import annotations

# Сколько секунд занимает одно повторение в среднем темпе.
SECONDS_PER_REP = 3


def calories_burned(*, met: float, weight_kg: float, minutes: float) -> float:
    """Расход за отрезок времени, ккал."""
    if met <= 0 or weight_kg <= 0 or minutes <= 0:
        return 0.0
    return met * weight_kg * (minutes / 60)


def strength_exercise_minutes(
    *, sets: int, reps: int, rest_seconds: int, seconds_per_rep: int = SECONDS_PER_REP
) -> float:
    """Сколько минут занимает упражнение вместе с отдыхом между подходами.

    Отдых считаем после каждого подхода, кроме последнего: после него человек
    переходит к следующему упражнению.
    """
    if sets <= 0 or reps <= 0:
        return 0.0
    work = sets * reps * seconds_per_rep
    rest = max(sets - 1, 0) * max(rest_seconds, 0)
    return (work + rest) / 60


def timed_exercise_minutes(*, sets: int, seconds_per_set: int, rest_seconds: int) -> float:
    """Планка и прочее «на время»: подход длится заданные секунды."""
    if sets <= 0 or seconds_per_set <= 0:
        return 0.0
    work = sets * seconds_per_set
    rest = max(sets - 1, 0) * max(rest_seconds, 0)
    return (work + rest) / 60


def strength_exercise_calories(
    *, met: float, weight_kg: float, sets: int, reps: int, rest_seconds: int
) -> float:
    """Расход на одно силовое упражнение."""
    return calories_burned(
        met=met,
        weight_kg=weight_kg,
        minutes=strength_exercise_minutes(sets=sets, reps=reps, rest_seconds=rest_seconds),
    )
