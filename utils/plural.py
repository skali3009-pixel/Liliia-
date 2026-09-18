"""Русские окончания при числах.

«1 записей» и «2 тренировок» выдают машину с головой, а приложение
разговаривает с человеком на его языке.
"""

from __future__ import annotations


def plural(count: int, one: str, few: str, many: str) -> str:
    """Слово в форме под число: 1 запись, 2 записи, 5 записей."""
    tail, hundred = abs(count) % 10, abs(count) % 100
    if 11 <= hundred <= 14:
        return many
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def with_count(count: int, one: str, few: str, many: str) -> str:
    """То же, но вместе с числом: «5 записей»."""
    return f"{count} {plural(count, one, few, many)}"


__all__ = ["plural", "with_count"]
