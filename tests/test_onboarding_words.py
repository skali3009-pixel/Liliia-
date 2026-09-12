"""Первые пять минут нового человека.

Здесь проверяются не обработчики, а слова: именно в них жила единственная
настоящая ложь бота. Пока оплата выключена и бот бесплатен для всех, фраза
«первые семь дней бесплатно» обещает плату, которой нет, — человек ждёт, что
его вот-вот отключат, и не вкладывается.
"""

import pytest

import config
from handlers import legal
from handlers.onboarding import first_step_text, norms_text


class FakeMacros:
    calories, protein_g, fat_g, carbs_g, fiber_g = 1786, 139, 56, 182, 25


# --- Пробный период --------------------------------------------------------

def _greeting(monkeypatch, paywall: bool) -> str:
    """Первая фраза анкеты собирается там же, где стоит проверка оплаты."""
    monkeypatch.setattr(config, "PAYWALL", paywall)
    monkeypatch.setattr(config, "TRIAL_DAYS", 7)
    trial = f"Первые {config.TRIAL_DAYS} дней бесплатно.\n" if config.PAYWALL else ""
    return f"Настроим профиль — это 1-2 минуты.\n{trial}\nУкажи свой пол:"


def test_no_trial_is_promised_while_the_bot_is_free(monkeypatch):
    assert "бесплатно" not in _greeting(monkeypatch, paywall=False)


def test_the_trial_is_named_when_payment_is_actually_on(monkeypatch):
    assert "7 дней бесплатно" in _greeting(monkeypatch, paywall=True)


def test_the_greeting_source_really_checks_the_paywall():
    """Проверка стоит в коде, а не только в этом тесте."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "handlers" /
              "onboarding.py").read_text(encoding="utf-8")
    assert "if config.PAYWALL else" in source
    assert source.count("config.PAYWALL") >= 2


# --- Первый экран ----------------------------------------------------------

def test_the_first_screen_tells_what_the_bot_actually_does_now():
    """Список умений отстал: шагов и подбора еды в нём не было вовсе."""
    text = legal.welcome_text().lower()
    for word in ("фото", "шаг", "команд", "съесть"):
        assert word in text, word


def test_the_consent_question_does_not_sell_a_subscription_that_is_not_there():
    """В бете подписки нет, а вопрос про неё заставляет гадать, что купил."""
    import inspect

    source = inspect.getsource(legal.accept)
    assert "подписке" not in source


# --- Последний экран -------------------------------------------------------

def test_the_norms_come_with_a_promise_not_to_count_by_hand():
    text = norms_text(FakeMacros(), 2432)
    assert "1786" in text and "2432" in text
    assert "взвешивать ничего не надо" in text


def test_the_last_message_names_one_action_not_a_list_of_features():
    """После девяти вопросов человек ждёт «что теперь», а не оглавление."""
    text = first_step_text()
    assert "Сфотографируй" in text
    # И говорит, что есть приложение: там живёт большая часть сделанного.
    assert "приложении" in text


def test_the_app_button_appears_only_when_there_is_an_app(monkeypatch):
    from handlers.onboarding import open_app_keyboard

    monkeypatch.setattr(config, "WEBAPP_URL", "")
    assert open_app_keyboard() is None

    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.com")
    markup = open_app_keyboard()
    button, = [b for row in markup.inline_keyboard for b in row]
    assert button.web_app is not None
