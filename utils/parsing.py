"""Разбор чисел, введённых пользователем в чат."""

from __future__ import annotations


def parse_int(text: str | None) -> int | None:
    try:
        return int(text.strip())
    except (AttributeError, TypeError, ValueError):
        return None


def parse_float(text: str | None) -> float | None:
    """Принимает и «68.5», и «68,5» — запятая как десятичный разделитель привычнее."""
    try:
        return float(text.strip().replace(",", "."))
    except (AttributeError, TypeError, ValueError):
        return None
