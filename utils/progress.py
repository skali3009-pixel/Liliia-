"""Визуализация дневного прогресса по норме (текстовый прогресс-бар)."""

from __future__ import annotations

FILLED_CHAR = "▓"
EMPTY_CHAR = "░"
DEFAULT_WIDTH = 10


def render_progress_bar(consumed: float, norm: float, *, width: int = DEFAULT_WIDTH) -> str:
    """Прогресс-бар вида `▓▓▓▓▓░░░░░ 52%`.

    Перебор нормы не ломает шкалу: бар заполняется целиком, а процент
    показывает реальное значение (например, 118%).
    """
    if width <= 0:
        raise ValueError("width должен быть положительным")
    if norm <= 0:
        return EMPTY_CHAR * width + " —"

    ratio = max(consumed / norm, 0.0)
    filled = min(int(round(ratio * width)), width)
    return f"{FILLED_CHAR * filled}{EMPTY_CHAR * (width - filled)} {round(ratio * 100)}%"


def format_remaining(consumed: float, norm: float) -> str:
    """«осталось 480 ккал» или «перебор на 120 ккал»."""
    remaining = round(norm - consumed)
    if remaining >= 0:
        return f"осталось {remaining}"
    return f"перебор на {abs(remaining)}"
