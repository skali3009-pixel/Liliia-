"""Остаток нормы на сегодня и чего именно не хватает."""

from __future__ import annotations

from dataclasses import dataclass

# Ниже этой доли остатка считаем, что макронутриент почти выбран.
NEARLY_DONE = 0.15


@dataclass(frozen=True)
class Remaining:
    calories: int
    protein_g: int
    fat_g: int
    carbs_g: int
    fiber_g: int = 0

    @property
    def all_done(self) -> bool:
        return self.calories <= 0


def remaining(totals: dict[str, float], norms: dict[str, float]) -> Remaining:
    """Сколько ещё можно съесть. Перебор показываем нулём, а не минусом."""
    return Remaining(
        calories=max(round(norms.get("calories", 0) - totals.get("calories", 0)), 0),
        protein_g=max(round(norms.get("protein_g", 0) - totals.get("protein_g", 0)), 0),
        fat_g=max(round(norms.get("fat_g", 0) - totals.get("fat_g", 0)), 0),
        carbs_g=max(round(norms.get("carbs_g", 0) - totals.get("carbs_g", 0)), 0),
        fiber_g=max(round(norms.get("fiber_g", 0) - totals.get("fiber_g", 0)), 0),
    )


def dominant_gap(left: Remaining, norms: dict[str, float]) -> str | None:
    """Какого макронутриента не хватает сильнее всего — по доле от нормы.

    Сравниваем именно доли: 40 г белка и 40 г углеводов при разных нормах
    означают разную степень недобора. Клетчатку здесь не учитываем: она не
    делит с БЖУ калорийность, у неё своя отдельная цель.
    """
    shares: dict[str, float] = {}
    for key, value in (("protein_g", left.protein_g), ("fat_g", left.fat_g),
                       ("carbs_g", left.carbs_g)):
        norm = norms.get(key, 0)
        if norm:
            shares[key] = value / norm

    if not shares:
        return None

    key, share = max(shares.items(), key=lambda item: item[1])
    return key if share > NEARLY_DONE else None


GAP_LABELS = {
    "protein_g": "белка",
    "fat_g": "жиров",
    "carbs_g": "углеводов",
}
