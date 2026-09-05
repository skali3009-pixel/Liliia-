"""Проверки вёрстки мини-приложения, которые ловятся без браузера.

Обе ошибки ниже уже случались: правило для кнопок нижней шторки растянуло
кнопки воды и вся страница поехала вбок, а главный экран открывался так, что
«сколько осталось» оказывалось ниже сгиба.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "webapp" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STYLES = (STATIC / "styles.css").read_text(encoding="utf-8")


def test_calories_come_before_the_input_block():
    """Кольцо с остатком — то, ради чего приложение открывают."""
    assert INDEX.index('class="ring-card"') < INDEX.index('class="capture"')


def test_nothing_pushes_the_ring_below_the_fold():
    """На экране телефона до кольца помещается только шапка."""
    ring = INDEX.index('class="ring-card"')
    for later in ('class="capture"', 'class="state-grid"', "<h2>Лента дня</h2>"):
        assert ring < INDEX.index(later), later


def test_sheet_button_rule_stays_inside_the_sheet():
    """`.row .chip` без области действия ломал ряд кнопок воды на всю ширину."""
    assert ".sheet .row .chip" in STYLES
    for line in STYLES.splitlines():
        stripped = line.strip()
        if stripped.startswith(".row .chip"):
            raise AssertionError(f"правило без области действия: {stripped}")
