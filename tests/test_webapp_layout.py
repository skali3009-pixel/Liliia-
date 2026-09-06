"""Проверки вёрстки мини-приложения, которые ловятся без браузера.

Обе ошибки ниже уже случались: правило для кнопок нижней шторки растянуло
кнопки воды и вся страница поехала вбок, а главный экран открывался так, что
«сколько осталось» оказывалось ниже сгиба.
"""

import re
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


APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")


def test_profile_sheet_elements_exist_for_every_id_the_code_wires():
    """Шестерёнка и поля профиля: код ищет их по id, опечатка ломает молча."""
    assert 'id="profile-open"' in INDEX
    for element_id in ("profile-sheet", "profile-close", "prof-goal", "prof-activity",
                       "prof-diet", "prof-height", "prof-age", "prof-target",
                       "prof-allergies", "prof-reminders", "prof-norms"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id


def test_meal_picker_and_recipe_sheet_are_wired():
    """Выбор приёма пищи и шторка рецепта: id должны совпадать с кодом."""
    for element_id in ("budget-line", "plate-hint", "suggest-btn", "suggestions",
                       "recipe-sheet", "recipe-close", "recipe-parts", "recipe-steps",
                       "recipe-eat", "recipe-title", "recipe-macros"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    # Кнопки приёмов пищи код ищет по классу, а не по id.
    assert 'class="meal-tab"' in INDEX and ".meal-tab" in APP_JS


def _visible_text(source: str) -> str:
    """Код без комментариев: подписи для человека живут только в строках."""
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", without_block)


def test_only_author_dishes_carry_a_mark():
    """Блюда сверх меню не помечаются ничем — так решила владелица бота."""
    assert "AUTHOR_MARK" in APP_JS
    assert "if (item.author)" in APP_JS
    visible = _visible_text(APP_JS)
    for label in ("по её принципам", "по принципам Анастасии", "сгенерировано",
                  "собрано по"):
        assert label not in visible, label
        assert label not in INDEX, label
