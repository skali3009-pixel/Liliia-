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


def test_the_turn_is_the_first_thing_after_the_hero():
    """«Твой ход» — самый умный блок приложения, и он стоит выше цифр."""
    today = INDEX.split('id="screen-today"')[1].split("</main>")[0]
    assert today.index('id="turn"') < today.index('class="quick"')
    assert today.index('class="quick"') < today.index('class="ring-card"')


def test_nothing_pushes_the_ring_below_the_fold():
    """До кольца помещаются только шапка, «Твой ход» и ряд быстрых действий."""
    ring = INDEX.index('class="ring-card"')
    for later in ('class="state-grid"', "<h2>Лента дня</h2>", "<h2>Задания дня</h2>"):
        assert ring < INDEX.index(later), later


def test_the_quick_row_leads_to_places_that_exist():
    """Четыре быстрых действия: мёртвая кнопка здесь заметнее всего."""
    for element_id in ("quick-food", "quick-water", "quick-move", "moment-open"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id


def test_one_button_is_the_main_one_on_the_day_screen():
    """Если главные все, главной нет ни одной."""
    today = INDEX.split('id="screen-today"')[1].split("</main>")[0]
    assert today.count('class="btn primary"') == 1
    assert '.btn.primary' in STYLES


def test_marking_how_she_feels_from_the_turn_actually_opens_a_tile():
    """Селектор искал button, а плитки состояния — div: кнопка молчала."""
    assert "'#state-grid .state'" in APP_JS
    assert ".state-grid button" not in APP_JS


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


def test_preps_section_is_wired():
    """Заготовки со сроками хранения — отдельный блок и своя шторка."""
    for element_id in ("preps-toggle", "preps-list", "prep-sheet", "prep-close",
                       "prep-title", "prep-macros", "prep-storage", "prep-parts",
                       "prep-steps", "prep-ideas"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id


CHAT = (Path(__file__).resolve().parent.parent / "handlers" /
        "suggestions.py").read_text(encoding="utf-8")


def _chat_strings() -> list[str]:
    """Строки, которые уходят человеку: без пояснений к коду."""
    import ast

    tree = ast.parse(CHAT)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docs]


def test_estimated_portions_are_disclosed():
    """Подобранные граммы нельзя показывать как авторские.

    Подбор блюд переехал из приложения в чат целиком — гарантия переехала
    вместе с ним, а не потерялась по дороге.
    """
    assert "offer.estimated" in CHAT
    assert "Порции подобраны" in CHAT


def test_only_author_dishes_carry_a_mark():
    """Блюда сверх меню не помечаются ничем — так решила владелица бота."""
    assert "AUTHOR_MARK" in CHAT
    # Смотрим только то, что человек увидит: правило описано и в пояснениях
    # к коду, но пояснения ему не показывают.
    shown = " ".join(_chat_strings())
    for label in ("по её принципам", "по принципам Анастасии", "сгенерировано",
                  "собрано по"):
        assert label not in shown, label
        assert label not in INDEX, label


def test_the_food_screen_answers_without_a_single_question():
    """Половина людей здесь не хочет отвечать на вопросы — им нужен ответ."""
    assert 'id="decide-btn"' in INDEX
    assert "'decide-btn'" in APP_JS
    assert "DECIDE_TEXT" in APP_JS
    # Обещание разное в каждом режиме: набор из магазина и блюдо из книги —
    # не одно и то же.
    for mode in ("cube:", "quick:", "book:", "preps:"):
        assert mode in APP_JS.split("DECIDE_TEXT")[1][:400], mode
    # И это единственная главная кнопка экрана.
    food = INDEX.split('id="screen-cube"')[1].split("</main>")[0]
    assert food.count('class="btn primary"') == 1


def test_the_food_screen_holds_all_four_answers():
    """Подбор блюд вернулся — но не на «Сегодня», а к Кубику, отдельным режимом.

    Повтором был не он: одинаковыми были подбор на «Сегодня» и та же кнопка
    в чате. Кубик отвечает на другой вопрос — «съесть, ничего не готовя», — и
    стоять рядом им не мешает, пока видно, что это разные вопросы.
    """
    for element_id in ("food-modes", "cube-mode", "menu-mode", "preps-card",
                       "suggest-btn", "recipe-sheet", "food-hint"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id

    # Четыре режима названы в одном месте, а не разбросаны по разметке.
    assert "FOOD_MODES" in APP_JS
    for mode in ("'cube'", "'quick'", "'book'", "'preps'"):
        assert mode in APP_JS, mode


def test_the_dish_picker_no_longer_stands_on_the_day_screen():
    """Ради этого его и убирали: «Сегодня» — про день, а не про выбор еды."""
    today = INDEX.split('id="screen-today"')[1].split("</main>")[0]
    for gone in ("suggest-btn", "meal-tab", "preps-toggle"):
        assert gone not in today, gone


def test_choosing_to_cook_is_a_mode_not_a_switch_inside_the_picker():
    """Переключатель «готовлю / не готовлю» дублировал бы выбор режима."""
    for gone in ("cook-opt", "cook-switch"):
        assert gone not in INDEX, gone
        assert gone not in APP_JS, gone


def test_shelf_photo_is_wired():
    """«Сфоткай полку»: скрытый input и карточка результата ищутся по id."""
    for element_id in ("shelf-input", "shelf-found"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    # Снимать надо заднюю камерой и сразу: полка перед человеком, а не в галерее.
    assert 'capture="environment"' in INDEX
    # Кнопка выбора файла — label, и без display:block она уезжает влево.
    assert "label.btn" in STYLES


def test_shelf_offer_comes_before_the_hand_marked_basket():
    """Сфотографировать проще, чем отмечать полсотни продуктов пальцем."""
    assert INDEX.index('id="cube-shelf-card"') < INDEX.index('id="cube-basket-card"')


def test_the_app_reports_its_own_breakage():
    """Ошибка в браузере не видна нигде — приложение должно сказать о ней само."""
    assert "addEventListener('error'" in APP_JS
    assert "unhandledrejection" in APP_JS
    assert "'/api/crash'" in APP_JS
    # Сломанный экран сыплет ошибками без конца — отчётов должно быть немного.
    assert "CRASH_LIMIT" in APP_JS


def test_the_problem_form_is_wired_in_the_app():
    """«Что-то не так» пишется там, где человек споткнулся, а не в чате."""
    for element_id in ("prof-problem", "prof-problem-send", "prof-problem-hint"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    assert "'/api/feedback'" in APP_JS


def test_the_step_ring_and_team_are_wired():
    """Кольцо шагов и команда: код ищет их по id, опечатка ломает молча."""
    for element_id in ("steps-fill", "steps-value", "steps-goal-label", "steps-left",
                       "steps-week", "steps-streak", "steps-add",
                       "team-create", "team-join", "team-leave", "team-invite",
                       "team-rows", "team-name-view", "top-rows", "top-place",
                       "prof-steps", "prof-steps-own"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id


def test_the_step_ring_stands_where_the_calorie_ring_stands():
    """Шаги открывают посмотреть сами по себе — им нужно место на первом экране."""
    assert INDEX.index('class="ring-card"') < INDEX.index('class="card steps-card"')
    assert INDEX.index('class="card steps-card"') < INDEX.index("<h2>Лента дня</h2>")


def test_the_person_is_told_that_steps_are_entered_by_hand():
    """Молчать об этом нельзя: человек решит, что шагомер сломался."""
    assert "Здоровье" in INDEX
    assert "сам" in INDEX or "сама" in INDEX


def test_the_automatic_sync_is_offered_in_the_app():
    """Вбивать шаги руками каждый день не будет почти никто."""
    for element_id in ("steps-sync", "sync-sheet", "sync-link", "sync-copy",
                       "sync-iphone", "sync-android", "sync-renew", "steps-synced"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    assert "'/api/steps/sync'" in APP_JS


def test_the_phone_hook_lives_outside_the_signed_api():
    """Стучится не приложение, а «Команды» по расписанию — подписи там нет."""
    api = (Path(__file__).resolve().parent.parent / "webapp" /
           "api.py").read_text(encoding="utf-8")
    assert '"/hook/steps/{token}"' in api
    assert '"/api/hook' not in api


def test_the_food_tab_is_called_by_what_it_holds():
    """Внутри четыре режима, и «Кубик» — имя только первого из них."""
    tabs = INDEX.split('<nav class="tabs">')[1].split("</nav>")[0]
    assert ">Еда</button>" in tabs
    assert ">Кубик</button>" not in tabs
    # А сам Кубик никуда не делся — он первый режим на этом экране.
    assert "'Кубик'" in APP_JS


def test_the_team_stands_where_it_gets_seen():
    """До команды приходилось листать полэкрана, а это самое живое на вкладке."""
    world = INDEX.split('id="screen-world"')[1].split("</main>")[0]
    assert world.index('id="team-card"') < world.index("<h2>Места</h2>")
    assert world.index('id="top-card"') < world.index("<h2>Открытия</h2>")
    # Но ближайшее открытие остаётся первым: ради него на вкладку возвращаются.
    assert world.index('id="world-next-card"') < world.index('id="team-card"')


def test_the_goal_moment_is_wired():
    """Дошла до цели — приложение обязано это заметить и спросить, что дальше."""
    for element_id in ("arrival", "arrival-text", "arrival-switch", "arrival-close"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    # Переход на поддержание делается в одно нажатие, а не поиском в анкете.
    assert "goal: 'maintain'" in APP_JS
