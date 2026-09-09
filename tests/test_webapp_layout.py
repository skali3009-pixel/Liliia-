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
                       "sync-android", "sync-renew", "steps-synced"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    assert "'/api/steps/sync'" in APP_JS


def test_the_setup_is_shown_one_step_at_a_time():
    """Полотном инструкцию не читают.

    В ней десять непривычных названий подряд («Найти данные Здоровья»,
    «Подсчитать статистику»), и человек теряет место после третьего — это
    и случилось с первой версией. Поэтому карточка, счётчик и две кнопки.
    """
    for element_id in ("guide-sheet", "guide-title", "guide-lead", "guide-steps",
                       "guide-note", "guide-back", "guide-next", "guide-count"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id

    body = APP_JS.split("function renderGuide(", 1)[1][:1200]
    assert "Шаг ${guideAt + 1} из ${cards.length}" in body, "человек должен видеть, сколько осталось"
    # Непроверенное на живом телефоне обязано выглядеть иначе, чем проверенное.
    assert "card.unverified" in body
    assert '[data-unverified="1"]' in STYLES


def test_the_ready_shortcut_button_is_hidden_until_the_server_offers_one():
    """Кнопка в никуда хуже, чем её отсутствие."""
    assert 'id="sync-ready" hidden' in INDEX
    body = APP_JS.split("async function openSync(", 1)[1][:3000]
    assert "ready.hidden = !(data.link && data.ready)" in body
    assert "tg?.openLink" in body


def test_a_dead_shortcut_link_still_leaves_a_way_to_set_steps_up():
    """Ссылка живёт в чужом облаке и однажды может перестать открываться.

    В короткой инструкции карточек сборки нет — значит, без выхода к ней
    человек остался бы совсем без шагов. Поэтому сервер всегда присылает и
    полный набор, а на карточке готовой команды есть кнопка к нему.
    """
    assert 'id="guide-manual" hidden' in INDEX
    body = APP_JS.split("function guideManual(", 1)[1][:600]
    assert "syncData.cards = syncData.all_cards" in body

    shown = APP_JS.split("function renderGuide(", 1)[1][:1400]
    assert "guide-manual').hidden = !card.ready" in shown


def test_the_connection_can_be_checked_from_the_app():
    """Настройка длинная, и её итог человек должен узнать от нас.

    Иначе остаётся ждать до полуночи и гадать, собралась связь или нет.
    """
    assert "'/api/steps/check'" in APP_JS
    for element_id in ("sync-check", "sync-state", "sync-state-title",
                       "sync-state-note"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id


def test_the_personal_link_is_hidden_until_asked():
    """Ссылку фотографируют и пересылают, не думая, что это ключ.

    Копировать её можно и не видя — значит, по умолчанию на экране её быть
    не должно.
    """
    assert 'id="sync-show"' in INDEX
    body = APP_JS.split("function maskLink(", 1)[1][:300]
    assert "••••••" in body
    opened = APP_JS.split("async function openSync(", 1)[1][:2500]
    assert "maskLink(data.link)" in opened


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


def test_the_sport_screen_offers_before_it_lists():
    """Тринадцать программ и семь форм — это выбор, а не занятие."""
    gym = INDEX.split('id="screen-gym"')[1].split("</main>")[0]
    assert gym.index('id="pick-card"') < gym.index('class="stats"')
    assert gym.index('id="pick-card"') < gym.index('id="category-switch"')
    # Подобранное первым — ответ, а не строка списка: у него своя кнопка.
    assert "pick-start" in APP_JS
    assert "Твоя тренировка сейчас" in APP_JS
    for minutes in ("5 минут", "15 минут", "30 минут", "45 минут"):
        assert f"'{minutes}'" in APP_JS, minutes
    # И каталог никуда не делся — он просто перестал встречать на входе.
    assert 'id="program-switch"' in gym and 'id="exercises"' in gym


def test_the_team_stands_where_it_gets_seen():
    """До команды приходилось листать полэкрана, а это самое живое на вкладке."""
    world = INDEX.split('id="screen-world"')[1].split("</main>")[0]
    assert world.index('id="team-card"') < world.index("<h2>Места</h2>")
    assert world.index('id="top-card"') < world.index("<h2>Открытия</h2>")
    # Но ближайшее открытие остаётся первым: ради него на вкладку возвращаются.
    assert world.index('id="world-next-card"') < world.index('id="team-card"')


def test_the_story_card_does_not_borrow_the_timeline_row_styles():
    """`.event` — строка ленты дня, и её display:flex разваливал карточку.

    Заголовок «Редкий день» переносился по слогам в узкую колонку, а текст
    события жался справа. Два разных смысла на одном имени класса.
    """
    assert 'class="card story" id="world-event"' in INDEX
    world = INDEX.split('id="screen-world"')[1].split("</main>")[0]
    assert 'class="event' not in world
    assert ".story {" in STYLES


def test_places_are_tiles_and_the_story_comes_early():
    """Мир должно быть видно, а не читать списком."""
    assert "#world-zones { display: grid" in STYLES
    assert ".place {" in STYLES
    assert "'place'" in APP_JS or "place${" in APP_JS
    # Имя не пересекается с зонами тела на «Прогрессе» — там свой `.zone`.
    assert ".zone ellipse" in STYLES
    world = INDEX.split('id="screen-world"')[1].split("</main>")[0]
    assert world.index('id="world-event"') < world.index('id="team-card"')


def test_the_measurement_form_asks_for_one_number_and_hides_the_rest():
    """Чаще всего записывают только вес, а пять строк «как мерить» над
    кнопкой сохранения читал один человек из десяти."""
    for element_id in ("measure-more", "measure-extra",
                       "measure-help", "measure-help-text"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    # Поля никуда не делись — они просто под кнопкой.
    for element_id in ("m-weight", "m-waist", "m-hips", "m-thigh", "m-chest", "m-arm"):
        assert f'id="{element_id}"' in INDEX, element_id
    progress = INDEX.split('id="screen-progress"')[1].split("</main>")[0]
    assert progress.count('class="btn primary"') == 1


def test_every_animation_can_be_switched_off_by_the_system():
    """«Уменьшить движение» — не украшение настроек.

    Человеку с чувствительностью к движению приложение должно остаться
    пригодным, а не просто «менее красивым». Поэтому весь блок движения
    живёт внутри `prefers-reduced-motion: no-preference`, а слой частиц
    прячется отдельным правилом.
    """
    motion = STYLES.split("Движение\n", 1)[1]
    assert "@media (prefers-reduced-motion: no-preference)" in motion
    assert "@media (prefers-reduced-motion: reduce)" in motion

    # Ни одна анимация не объявлена снаружи этих скобок.
    outside = re.split(r"@media \(prefers-reduced-motion[^)]*\)", motion)[0]
    assert "animation:" not in outside, "анимация мимо настройки «уменьшить движение»"

    # И код тоже спрашивает разрешения, а не только стили.
    assert "prefers-reduced-motion: reduce" in APP_JS
    for helper in ("function sparks(", "function flyReward(", "function countTo(",
                   "function playEntrance("):
        body = APP_JS.split(helper, 1)[1][:900]
        assert "motion()" in body, helper


def test_particles_are_cleaned_up_and_capped():
    """Частица — отдельный слой в браузере. Забыть их убрать значит

    посадить телефон: их станет тысяча, и прокрутка начнёт дёргаться.
    """
    assert "SPARK_LIMIT" in APP_JS
    for helper in ("function sparks(", "function flyReward("):
        body = APP_JS.split(helper, 1)[1][:1800]
        assert "animationend" in body, helper
        assert ".remove()" in body, helper


def test_the_ring_flashes_when_the_goal_closes_and_not_on_every_redraw():
    """Экран перерисовывается после каждого стакана воды.

    Без памяти о прошлом состоянии кольцо вспыхивало бы каждый раз, и
    вспышка перестала бы что-либо значить.
    """
    assert "doneBefore" in APP_JS
    body = APP_JS.split("function markDone(", 1)[1][:600]
    assert "was !== false" in body


def test_no_blanket_rule_moves_the_crop_down_the_picture():
    """У каждой картинки зверь на своей высоте — общего числа не бывает.

    Один раз попробовали: чтобы вытащить зверя в узкую шапку «Спорта», окно
    сдвинули на 42% вниз сразу у всех узких шапок. «Спорту» помогло, а на
    «Прогрессе» ровно в середине кадра оказались спина и хвост — шапка стала
    показывать заднюю часть гепарда. Правильный ответ был не в проценте, а в
    том, чтобы у «Спорта» был горизонтальный кадр.
    """
    for line in STYLES.splitlines():
        stripped = line.strip()
        if "background-position" not in stripped or stripped.startswith("/*"):
            continue
        # Разрешены только края: top/center/right. Проценты по вертикали —
        # это и есть попытка угадать одно место для всех картинок.
        assert "%" not in stripped or "background-position: 0 0" in stripped, (
            f"сдвиг окна по кадру общим правилом: {stripped}")


def test_the_goal_moment_is_wired():
    """Дошла до цели — приложение обязано это заметить и спросить, что дальше."""
    for element_id in ("arrival", "arrival-text", "arrival-switch", "arrival-close"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    # Переход на поддержание делается в одно нажатие, а не поиском в анкете.
    assert "goal: 'maintain'" in APP_JS


def test_one_header_shows_one_cheetah():
    """Под шапкой не лежит вторая картинка — иначе она мелькает.

    Запасной слой задумывался как страховка: не скачался один файл — виден
    следующий. Но браузер грузит все слои сразу и рисует тот, что успел
    первым. Гепард с «Сегодня» уже лежал в памяти телефона, и на «Моём мире»
    он вспыхивал на долю секунды, а потом подменялся своим. То же на
    «Прогрессе» и «Еде». Проверено в браузере: если верхнюю картинку не
    отдать, под «Моим миром» оставался hero, под «Прогрессом» — world, под
    «Едой» — moment.

    Страховка от нескачанного файла — градиент со звёздами. Он нарисован
    кодом, ждать его не нужно, и подменить картинку он не может.
    """
    # Правила собираем целиком: background-image бывает в несколько строк.
    for rule in re.findall(r"background-image:[^;]*;", STYLES):
        pictures = re.findall(r"url\(", rule)
        assert len(pictures) <= 1, f"две картинки в одной шапке: {' '.join(rule.split())}"


def test_notification_settings_are_wired_in_the_app():
    """Семь галочек, частота и тихие часы — и всё это связано с кодом.

    Настройки, которые видно, но которые ничего не меняют, хуже отсутствия
    настроек: человек считает, что выключил, и продолжает получать.
    """
    for element_id in ("notif-toggle", "notif-box", "notif-kinds", "notif-pace",
                       "notif-from", "notif-to"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    # Настройки уходят на сервер тем же запросом, что и профиль.
    assert "notifications:" in APP_JS


def test_the_categories_the_app_shows_are_the_ones_the_engine_knows():
    """Галочка «Вода» обязана выключать именно воду.

    Список для экрана и список, по которому движок решает, — разные места.
    Разойдутся — человек снимет галочку, а сообщения останутся.
    """
    import re as _re
    from models.notification import KINDS

    api = (Path(__file__).resolve().parents[1] / "webapp" / "api.py").read_text(
        encoding="utf-8")
    block = api.split("NOTIFY_LABELS = (", 1)[1].split(")\n", 1)[0]
    shown = set(_re.findall(r'\("(\w+)",', block))
    assert shown == set(KINDS)


def test_the_cycle_calendar_is_wired_in_the_app():
    """Календарь стоит на «Прогрессе» рядом с весом — там, где он и нужен.

    Он не про календарь, а про то, чтобы объяснить прибавку перед
    месячными в ту минуту, когда человек смотрит на график и решает, что
    всё зря.
    """
    for element_id in ("cycle-card", "cycle-phase", "cycle-weight",
                       "cycle-strip", "cycle-mark", "cycle-disclaimer"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id

    # Именно на «Прогрессе», а не где придётся.
    progress = INDEX.split('id="screen-progress"', 1)[1].split("</main>", 1)[0]
    assert 'id="cycle-card"' in progress


def test_the_cycle_can_be_switched_off_from_the_profile():
    """Женщине он может быть просто не нужен, а мужчине бессмыслен."""
    assert 'id="prof-cycle"' in INDEX
    assert "prof-cycle-row" in APP_JS
    assert "'female'" in APP_JS      # строка настройки скрыта не для всех


def test_the_cycle_strip_opens_on_today():
    """Человек пришёл отметить сегодня, а не листать месяц назад."""
    body = APP_JS.split("function renderCycleStrip(", 1)[1][:1400]
    assert "scrollLeft" in body


def test_the_activity_card_is_above_the_catalogue():
    """Отметить пробежку хотят чаще, чем выбирать программу.

    Раньше этот список лежал внизу экрана и показывался только в «Теле» —
    человек, пришедший за йогой, его просто не видел. Кнопки выбора теперь
    стоят выше него, но сам он от этого не опустился: он по-прежнему перед
    каталогом упражнений.
    """
    gym = INDEX.split('id="screen-gym"', 1)[1].split("</main>", 1)[0]
    assert gym.index("cardio-card") < gym.index('id="exercises"')
    assert "Я занималась сама" in gym


def test_the_choice_buttons_come_right_after_the_picker():
    """Замерено в браузере: раньше фильтры начинались на 1626-й точке.

    Между подбором и ими лежал список занятий высотой 1180 точек — половина
    всей страницы, — и человек, который хочет выбрать сам, до кнопок просто
    не доходил. Теперь порядок такой: подбор, кнопки, занятия, каталог, а
    итог недели — в конце: он ничем не управляет.
    """
    gym = INDEX.split('id="screen-gym"', 1)[1].split("</main>", 1)[0]
    order = [gym.index(mark) for mark in (
        'id="pick-card"', 'class="filters"', 'id="program-switch"',
        'id="cardio-card"', 'id="exercises"', 'class="stats"')]
    assert order == sorted(order), "порядок блоков «Спорта» изменился"


def test_activities_are_marked_by_tiles_not_by_rows():
    """Двенадцать строк с подходами и ссылкой — это половина страницы.

    От человека здесь нужно одно слово: что он делал. Минуты спросим при
    записи — и это честнее готового «40 мин», которого он не выбирал.
    """
    assert 'id="cardio-list"' in INDEX
    assert 'class="chips wrap" id="cardio-list"' in INDEX
    assert ".chips.wrap" in STYLES

    body = APP_JS.split("function renderWorkouts(", 1)[1][:2000]
    assert "cardio.appendChild(cardioChip(exercise))" in body
    # Отметка и фильтр выглядят одинаково — значит, отметку надо отличать.
    chip = APP_JS.split("function cardioChip(", 1)[1][:900]
    assert "✓" in chip
    assert "doneExercises.delete" in chip and "doneExercises.add" in chip


def test_the_activity_is_confirmed_where_it_was_marked():
    """Отметила пробежку наверху — подтвердила там же.

    Одна кнопка внизу означала бы, что человек листает до конца каталога
    упражнений ради занятия, которое отметил в самом начале. Проверено в
    браузере: с того места, где стоят плитки, кнопка видна без прокрутки.
    """
    gym = INDEX.split('id="screen-gym"', 1)[1].split("</main>", 1)[0]
    card = gym.split('id="cardio-card"', 1)[1].split("</section>", 1)[0]
    assert 'id="finish-cardio"' in card, "кнопка должна жить в карточке занятий"

    # Каждая кнопка записывает своё: иначе нажатие в одной карточке уносит
    # отметки из другой, и человек об этом не узнает.
    runs = APP_JS.split("async function finishCardio(", 1)[1][:700]
    assert "cardioIds.has(id)" in runs and "!cardioIds.has(id)" not in runs
    moves = APP_JS.split("async function finishWorkout(", 1)[1][:400]
    assert "!cardioIds.has(id)" in moves


def test_minutes_are_said_to_be_counted_for_each_activity():
    """Полчаса бега и полчаса скакалки — это час, а не полчаса.

    Минуты записываются каждому отмеченному занятию. Пока плитку было
    трудно нажать, это почти не встречалось; теперь отметить две — одно
    движение, и молчать об этом нельзя.
    """
    body = APP_JS.split("function askMinutes(", 1)[1][:400]
    assert "на каждое" in body
    call = APP_JS.split("async function finishCardio(", 1)[1][:700]
    assert "askMinutes(ids.length > 1)" in call


def test_the_record_button_has_one_owner():
    """Двое хозяев у одной кнопки — это спор, который кто-то проигрывает.

    Предупреждение прятало кнопку записи, а обновление показывало её
    обратно: вызывается оно следом. Теперь прячет только один, и он
    смотрит на предупреждение.
    """
    warning = APP_JS.split("function renderGymWarning(", 1)[1][:700]
    assert "finish" not in warning.split("if (!needed) return;")[0].replace(
        "// Кнопку записи прячет updateFinishButton — она вызывается следом и", "")

    body = APP_JS.split("function updateFinishButton(", 1)[1][:900]
    assert "gym-warning" in body


def test_the_personal_topic_is_hidden_until_it_is_read():
    """Предупреждение занимает место упражнений, а не висит над ними."""
    for element_id in ("gym-warning", "gym-warning-text", "gym-warning-ok"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id
    # Проверка текстовая — код в браузере отсюда не запустить. Поэтому
    # сверяем не наличие слова, а само выражение: «список скрыт ровно
    # тогда, когда предупреждение не прочитано». Первая версия искала
    # подстроку «list.hidden» и спокойно пропускала «list.hidden = false».
    body = APP_JS.split("function renderGymWarning(", 1)[1][:900]
    assert "list.hidden = !!needed" in body


def test_numbers_are_asked_in_our_own_window():
    """Системное окно браузера выглядит чужим и обрезает текст на телефоне.

    Спрашиваем числа три раза: минуты занятия, шаги за день, граммы в
    порции. Проверка общая — по всему файлу, потому что заменены все три:
    проверка «в этой функции нет prompt» пропустила бы четвёртое окно,
    добавленное завтра рядом.
    """
    assert "prompt(" not in APP_JS
    # Со скобкой без содержимого не сверяемся: у askMinutes появился
    # признак «отмечено несколько», и проверка на «askMinutes()» падала бы
    # из-за него, ничего не поймав.
    for name in ("askMinutes(", "askNumber({"):
        assert name in APP_JS, name
    for element_id in ("number-sheet", "number-choices", "number-own",
                       "number-title", "number-hint", "number-label"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id


def test_the_are_you_sure_questions_are_ours_too():
    """«ОК» и «Отмена» системного окна не говорят, что именно случится.

    Поэтому проверяется не только своё окно, но и то, ради чего оно
    заведено: на кнопке написано действие («Удалить», «Выйти»,
    «Сменить»), а отказаться можно двумя способами — крестиком и
    «Отменой», — и оба безопасны.
    """
    assert "confirm(" not in APP_JS
    for element_id in ("confirm-sheet", "confirm-title", "confirm-text",
                       "confirm-yes", "confirm-no", "confirm-close"):
        assert f'id="{element_id}"' in INDEX, element_id
        assert f"'{element_id}'" in APP_JS, element_id

    body = APP_JS.split("function askYes(", 1)[1][:1200]
    assert body.count("close(false)") == 2, "отказ должен быть и у крестика"

    # Кнопка по умолчанию называется «Да» — это ровно то, чего мы избегали.
    # Значит, действие обязан назвать каждый, кто спрашивает.
    asks = APP_JS.split("await askYes({")[1:]
    assert len(asks) >= 6
    for piece in asks:
        head = piece[:400]
        assert "action:" in head, head[:120]
        # Заголовок окна набран капсом и вразрядку. Название блюда в нём
        # разворачивается на три строки и наезжает на крестик — проверено
        # в браузере на экране 320 точек. Название живёт строкой ниже.
        title = head.split("title:", 1)[1].split(",", 1)[0]
        assert "${" not in title, title


def test_the_step_window_offers_no_round_numbers():
    """Шаги переписывают с телефона.

    Кнопка «8000» вместо пройденных 7412 — это не удобство, а неправда в
    дневнике: она попадёт и в неделю, и в рейтинг команды.
    """
    body = APP_JS.split("async function askSteps(", 1)[1][:700]
    assert "choices" not in body
    assert "askNumber({" in body
