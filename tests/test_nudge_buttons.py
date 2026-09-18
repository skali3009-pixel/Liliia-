"""Кнопки под подсказкой бота и ссылки, ведущие в нужную вкладку.

Кнопка, которая ничего не меняет, хуже её отсутствия: она учит, что бота
слушать бесполезно. Поэтому здесь проверяется не вид кнопок, а то, что за
каждой стоит настоящее действие.
"""

import config
from keyboards.notifications import (CB_LATER, CB_MUTE, CB_WATER, SCREEN,
                                     deep_link, nudge_keyboard)
from models.notification import KINDS, KIND_WATER


def buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_water_is_added_without_leaving_the_chat():
    markup = nudge_keyboard(target="water", cta="+250 мл", kind=KIND_WATER,
                            amount=250)
    first = buttons(markup)[0]
    assert first.callback_data == f"{CB_WATER}250"
    assert first.web_app is None       # именно в чате, а не «откройте приложение»


def test_every_nudge_can_be_stopped_without_switching_the_bot_off():
    markup = nudge_keyboard(target="cube", cta="Подобрать еду", kind="meal")
    data = [button.callback_data for button in buttons(markup)]
    assert f"{CB_LATER}meal" in data
    assert f"{CB_MUTE}meal" in data


def test_the_button_opens_the_tab_where_the_action_happens(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.test/app")
    markup = nudge_keyboard(target="workout", cta="Подобрать движение",
                            kind="movement")
    opener = buttons(markup)[0]
    assert opener.web_app is not None
    # Не главный экран: человек, нажавший «подобрать движение», не должен
    # искать нужную вкладку сам.
    assert opener.web_app.url.endswith("screen=gym")


def test_without_an_app_address_the_message_still_has_its_stop_buttons(monkeypatch):
    """Приложение может быть не настроено — сообщение всё равно управляемо."""
    monkeypatch.setattr(config, "WEBAPP_URL", "")
    markup = nudge_keyboard(target="cube", cta="Подобрать еду", kind="meal")
    data = [button.callback_data for button in buttons(markup)]
    assert data == [f"{CB_LATER}meal", f"{CB_MUTE}meal"]


def test_every_target_the_advice_can_have_leads_somewhere(monkeypatch):
    """Совет, которому некуда вести, — это кнопка в никуда."""
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.test/app")
    from services.context import _candidates, DayContext

    # Собираем все цели, которые вообще умеет выдавать подсказка.
    rich = DayContext(
        hour=15, calories=100, calories_target=2000, protein_g=5, protein_target=100,
        fiber_g=1, fiber_target=25, water_ml=0, water_target=2000, meals_logged=0,
        steps=100, steps_goal=8000, steps_logged=True, workouts_today=0,
        days_since_measure=30, energy=5, checkin_done=False, preps_expiring=("щи",),
    )
    targets = {action.target for action in _candidates(rich)}
    assert targets, "подсказка не выдала ни одного кандидата — проверять нечего"
    for target in targets:
        assert target in SCREEN, f"совету «{target}» некуда вести"
        assert deep_link(target)


def test_stop_buttons_name_only_real_categories():
    """Категория, которую ставит движок, должна быть известна обработчику
    нажатия. Разойдутся — «позже» промолчит, и человек решит, что кнопка
    сломана."""
    from services.notifications import KIND_OF

    assert set(KIND_OF.values()) <= set(KINDS)
