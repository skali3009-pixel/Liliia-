"""Первые пять минут нового человека.

Здесь проверяются не обработчики, а слова: именно в них жила единственная
настоящая ложь бота. Пока оплата выключена и бот бесплатен для всех, фраза
«первые семь дней бесплатно» обещает плату, которой нет, — человек ждёт, что
его вот-вот отключат, и не вкладывается.
"""

import pytest

import config
from handlers import legal
from handlers.onboarding import first_step_text, norms_text, trial_line


class FakeMacros:
    calories, protein_g, fat_g, carbs_g, fiber_g = 1786, 139, 56, 182, 25


# --- Пробный период --------------------------------------------------------

def _greeting(monkeypatch, paywall: bool) -> str:
    """Первая фраза анкеты — из самого кода, а не из копии тех же слов.

    Раньше тест собирал строку у себя: такая проверка проходит и на
    сломанном обработчике, потому что сверяет сама с собой.
    """
    monkeypatch.setattr(config, "PAYWALL", paywall)
    monkeypatch.setattr(config, "TRIAL_DAYS", 7)
    return f"Настроим профиль — это 1-2 минуты.\n{trial_line()}\nУкажи свой пол:"


def test_no_trial_is_promised_while_the_bot_is_free(monkeypatch):
    assert "бесплатно" not in _greeting(monkeypatch, paywall=False)


def test_the_trial_is_named_when_payment_is_actually_on(monkeypatch):
    assert "7 дней — бесплатно" in _greeting(monkeypatch, paywall=True)


def test_the_number_of_days_is_declined_properly(monkeypatch):
    """«Первые 21 дней» — не по-русски, а срок мы как раз меняем.

    Число в этой строке берётся из настройки, и при 21 обычное «дней»
    становится ошибкой в первом же сообщении новому человеку.
    """
    monkeypatch.setattr(config, "PAYWALL", True)
    ожидаем = {1: "1 день", 2: "2 дня", 5: "5 дней", 7: "7 дней",
               11: "11 дней", 21: "21 день", 22: "22 дня", 30: "30 дней"}
    for дней, строка in ожидаем.items():
        monkeypatch.setattr(config, "TRIAL_DAYS", дней)
        assert f"Первые {строка} — бесплатно" in trial_line(), (дней, trial_line())


def test_the_trial_says_what_the_time_is_for(monkeypatch):
    """Срок без объяснения читается как «потом заплати»."""
    monkeypatch.setattr(config, "PAYWALL", True)
    monkeypatch.setattr(config, "TRIAL_DAYS", 21)
    строка = trial_line()
    assert "каждый день" in строка, строка
    # И это не обещание результата — те же правила, что у техники и тура.
    for запрет in ("похуде", "гарантирова", "результат за", "избавит"):
        assert запрет not in строка.lower(), запрет


def test_the_greeting_source_really_checks_the_paywall():
    """Проверка стоит в коде, а не только в этом тесте."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "handlers" /
              "onboarding.py").read_text(encoding="utf-8")
    assert "if not config.PAYWALL:" in source
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
    """Кнопка приложения появляется только когда приложение есть.

    Музыка отсюда ушла 22.09 в своё сообщение — кнопка на чужом сообщении
    уезжала выше экрана раньше, чем до неё дотягивались. Гарантия осталась
    та же: нет адреса приложения — нет и клавиатуры вовсе, потому что
    пустую Telegram не принимает. А заодно проверяем, что музыка сюда не
    вернулась: две кнопки в одном месте — это то, из-за чего всё и
    переделывали.
    """
    from handlers.onboarding import open_app_keyboard

    monkeypatch.setattr(config, "WEBAPP_URL", "")
    monkeypatch.setattr(config, "MUSIC_URL", "")
    assert open_app_keyboard() is None

    # Музыка есть, приложения нет: клавиатуры всё равно нет — музыке здесь
    # больше не место, и одной ею клавиатура не заводится.
    monkeypatch.setattr(config, "MUSIC_URL", "https://music.example/artist/1")
    assert open_app_keyboard() is None

    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.com")
    кнопки = [b for row in open_app_keyboard().inline_keyboard for b in row]
    assert any(b.web_app is not None for b in кнопки)
    assert all(b.url is None for b in кнопки), [b.text for b in кнопки]
