"""Что происходит, когда что-то ломается.

Проверка появилась после случая, который стоит помнить: из save_meal убрали
параметр, вызов в обработчике остался, и еда из чата перестала сохраняться
совсем. Ошибка легла в лог, человек видел тишину, владелец не знал ничего.
Узнали от живой девочки через несколько дней.

Поэтому здесь проверяется не текст, а то, что о поломке узнают обе стороны
и что сообщений об одной и той же поломке не будет пачкой.
"""

import asyncio
from datetime import timedelta

import pytest

import config
from handlers import errors as error_handler
from services import alerts, crashes

OWNER = 246959020


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    crashes.reset()
    alerts.reset()
    monkeypatch.setattr(config, "ADMIN_IDS", [OWNER])
    monkeypatch.setattr(crashes.config, "ADMIN_IDS", [OWNER])
    monkeypatch.setattr(alerts.config, "ADMIN_IDS", [OWNER])
    yield
    crashes.reset()
    alerts.reset()


class FakeBot:
    def __init__(self, failing: bool = False):
        self.sent: list[tuple[int, str]] = []
        self.failing = failing

    async def send_message(self, chat_id, text, **kwargs):
        if self.failing:
            raise RuntimeError("владелец заблокировал бота")
        self.sent.append((chat_id, text))


def boom(message: str = "так вышло") -> Exception:
    """Настоящая ошибка с настоящей трассировкой через наш код."""
    try:
        _explode(message)
    except Exception as error:  # noqa: BLE001
        return error
    raise AssertionError("не сломалось")


def _explode(message: str):
    raise TypeError(message)


def run(scenario):
    asyncio.run(scenario())


# --- Как выглядит поломка --------------------------------------------------

def test_the_place_points_at_our_own_code():
    """В трассировке последние кадры почти всегда чужие — нужен наш."""
    place = crashes.where_in_code(boom())
    assert place.startswith("tests/test_crashes.py:")
    assert "_explode" in place


def test_the_description_is_one_line_with_type_and_text():
    assert crashes.describe(boom("нет такого параметра")) == \
        "TypeError: нет такого параметра"


def test_different_breakages_are_told_apart():
    def other():
        try:
            raise ValueError("другое")
        except Exception as error:  # noqa: BLE001
            return error

    assert crashes.signature(boom()) != crashes.signature(other())


def test_the_same_breakage_from_the_same_place_has_one_signature():
    assert crashes.signature(boom("раз")) == crashes.signature(boom("два"))


# --- Кому и сколько раз ----------------------------------------------------

def test_the_owner_is_told_where_it_broke():
    async def scenario():
        bot = FakeBot()
        assert await crashes.report(bot, boom("нет такого параметра"),
                                    where="чат", user_id=707)

        (chat_id, text), = bot.sent
        assert chat_id == OWNER
        assert "нет такого параметра" in text
        assert "tests/test_crashes.py:" in text
        assert "707" in text
    run(scenario)


def test_the_same_breakage_is_reported_once_not_in_a_flood():
    """Поломка в частом месте повторяется десятки раз в минуту."""
    async def scenario():
        bot = FakeBot()
        for _ in range(20):
            await crashes.report(bot, boom(), where="чат")
        assert len(bot.sent) == 1
    run(scenario)


def test_a_different_breakage_still_gets_through():
    async def scenario():
        bot = FakeBot()
        await crashes.report(bot, boom(), where="чат")

        def other():
            try:
                raise KeyError("совсем другое")
            except Exception as error:  # noqa: BLE001
                return error

        await crashes.report(bot, other(), where="чат")
        assert len(bot.sent) == 2
    run(scenario)


def test_the_same_breakage_returns_after_the_quiet_half_hour():
    async def scenario():
        bot = FakeBot()
        await crashes.report(bot, boom(), where="чат")
        # Отматываем отметку назад — как будто прошло больше получаса.
        for key in list(crashes._seen):
            crashes._seen[key] -= crashes.COOLDOWN + timedelta(minutes=1)

        await crashes.report(bot, boom(), where="чат")
        assert len(bot.sent) == 2
    run(scenario)


def test_reporting_never_breaks_on_top_of_a_breakage():
    """Сообщение о поломке не имеет права уронить ответ человеку."""
    async def scenario():
        assert await crashes.report(FakeBot(failing=True), boom(), where="чат") is False
        assert await crashes.report(None, boom("без бота"), where="чат") is False
    run(scenario)


def test_nothing_is_sent_when_there_is_no_owner(monkeypatch):
    async def scenario():
        monkeypatch.setattr(crashes.config, "ADMIN_IDS", [])
        bot = FakeBot()
        assert await crashes.report(bot, boom(), where="чат") is False
        assert bot.sent == []
    run(scenario)


# --- Что видит человек -----------------------------------------------------

class FakeHolder:
    def __init__(self):
        self.said: list[str] = []

    async def answer(self, text, **kwargs):
        self.said.append(text)


class FakeCallback:
    def __init__(self, holder):
        self.message = holder
        self.from_user = type("U", (), {"id": 707})()
        self.closed = False

    async def answer(self, text="", **kwargs):
        self.closed = True


class FakeEvent:
    def __init__(self, exception, update):
        self.exception = exception
        self.update = update


def _update(*, message=None, callback=None):
    return type("Update", (), {"message": message, "callback_query": callback,
                               "edited_message": None})()


def test_the_person_hears_that_it_is_not_their_fault():
    async def scenario():
        holder = FakeHolder()
        holder.from_user = type("U", (), {"id": 707})()
        bot = FakeBot()

        await error_handler.on_error(FakeEvent(boom(), _update(message=holder)), bot)

        assert holder.said, "человек остался с тишиной"
        text = holder.said[0]
        assert "не у тебя" in text and "целы" in text
        # Ни трассировки, ни файлов: человеку они бесполезны, а пугают.
        assert "Traceback" not in text and ".py" not in text
    run(scenario)


def test_a_broken_button_stops_spinning():
    """Иначе кнопка так и висит с индикатором, и человек жмёт её снова."""
    async def scenario():
        holder = FakeHolder()
        callback = FakeCallback(holder)
        await error_handler.on_error(
            FakeEvent(boom(), _update(callback=callback)), FakeBot())

        assert callback.closed
        assert holder.said
    run(scenario)


def test_the_owner_learns_who_it_happened_to():
    async def scenario():
        holder = FakeHolder()
        callback = FakeCallback(holder)
        bot = FakeBot()

        await error_handler.on_error(
            FakeEvent(boom("нет такого параметра"), _update(callback=callback)), bot)

        (_, text), = bot.sent
        assert "707" in text and "нет такого параметра" in text
    run(scenario)


def test_a_breakage_without_anyone_to_answer_still_reaches_the_owner():
    """Падение в фоновой задаче: отвечать некому, сообщить всё равно надо."""
    async def scenario():
        bot = FakeBot()
        await error_handler.on_error(FakeEvent(boom(), _update()), bot)
        assert len(bot.sent) == 1
    run(scenario)
