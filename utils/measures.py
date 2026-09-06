"""Перевод бытовых мер в граммы.

В рецептах нутрициолога рядом с граммами стоят «2 ст. л.», «горсть зелени»,
«1 зубчик», «½ шт». Считать по ним КБЖУ нельзя, пока они не станут числом.

Это допущения, а не данные из файлов, поэтому они живут отдельным явным
списком: видно, где кончается источник и начинается наша оценка.
"""

from __future__ import annotations

# Ложка ложке рознь: столовая ложка масла и столовая ложка мёда весят разное.
SPOON_G = {
    "масло": 15.0, "мёд": 21.0, "соевый соус": 15.0, "йогурт": 25.0,
    "паста": 25.0, "сухари": 15.0, "мука": 12.0, "сок": 15.0, "какао": 6.0,
    "сметана": 25.0, "тахини": 20.0,
}
TEASPOON_G = {
    "масло": 5.0, "мёд": 8.0, "соевый соус": 5.0, "сок": 5.0, "какао": 3.0,
    "горчица": 5.0, "сахар": 5.0, "паста": 8.0,
}

# Прочее, что встречается в рецептах.
HANDFUL_G = 15.0       # горсть зелени/шпината/рукколы
PINCH_G = 0.0          # щепотка специй — на КБЖУ не влияет
CLOVE_G = 3.0          # зубчик чеснока
SLICE_BREAD_G = 30.0   # ломтик цельнозернового хлеба

DEFAULT_SPOON_G = 15.0
DEFAULT_TEASPOON_G = 5.0


def _lookup(table: dict[str, float], product_name: str, default: float) -> float:
    name = (product_name or "").lower()
    for key, grams in table.items():
        if key in name:
            return grams
    return default


def spoon(product_name: str = "") -> float:
    """Столовая ложка продукта в граммах."""
    return _lookup(SPOON_G, product_name, DEFAULT_SPOON_G)


def teaspoon(product_name: str = "") -> float:
    """Чайная ложка продукта в граммах."""
    return _lookup(TEASPOON_G, product_name, DEFAULT_TEASPOON_G)


def piece(gram_per_piece: float | None, count: float = 1.0) -> float:
    """Штуки в граммы. Без веса штуки считать нечего — честный ноль."""
    return round((gram_per_piece or 0.0) * count, 1)


__all__ = ["CLOVE_G", "HANDFUL_G", "PINCH_G", "SLICE_BREAD_G", "piece", "spoon", "teaspoon"]
