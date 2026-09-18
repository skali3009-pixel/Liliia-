"""Срочные сигналы владельцу: приходят в моменте и не превращаются в спам."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import config
from services import alerts


class FakeBot:
    """Ловит то, что бот попытался отправить владельцу."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {246959020})
    alerts.reset()
    yield
    alerts.reset()


def run(scenario):
    asyncio.run(scenario())


def test_signal_reaches_the_owner_at_once():
    async def scenario():
        bot = FakeBot()
        assert await alerts.fire(bot, alerts.DISK, "warn", "диск 81%")
        assert bot.sent == [(246959020, "диск 81%")]
    run(scenario)


def test_the_same_trouble_is_reported_once():
    """Сигнал каждые десять минут перестают читать через день."""
    async def scenario():
        bot = FakeBot()
        await alerts.fire(bot, alerts.DISK, "warn", "диск 81%")
        await alerts.fire(bot, alerts.DISK, "warn", "диск 81%")
        await alerts.fire(bot, alerts.DISK, "warn", "диск 82%")
        assert len(bot.sent) == 1
    run(scenario)


def test_worsening_is_a_new_event():
    """«Кончается» и «кончилось» — разные новости."""
    async def scenario():
        bot = FakeBot()
        await alerts.fire(bot, alerts.DISK, "warn", "диск 81%")
        await alerts.fire(bot, alerts.DISK, "full", "диск 91%")
        assert len(bot.sent) == 2
    run(scenario)


def test_owner_learns_that_it_let_go():
    async def scenario():
        bot = FakeBot()
        await alerts.fire(bot, alerts.DISK, "warn", "диск 81%")
        assert await alerts.resolve(bot, alerts.DISK, "всё в порядке")
        assert bot.sent[-1][1] == "всё в порядке"

        # Второй раз сообщать не о чем.
        assert await alerts.resolve(bot, alerts.DISK, "всё в порядке") is False
    run(scenario)


def test_calm_never_reported_on_its_own():
    """Без тревоги «всё хорошо» — тоже спам."""
    async def scenario():
        bot = FakeBot()
        assert await alerts.resolve(bot, alerts.DISK, "всё в порядке") is False
        assert bot.sent == []
    run(scenario)


def test_flood_is_capped():
    """Что бы ни случилось, владельца не заваливает."""
    async def scenario():
        bot = FakeBot()
        for i in range(alerts.MAX_PER_HOUR + 4):
            await alerts.fire(bot, alerts.DISK, f"state-{i}", f"сигнал {i}")
        assert len(bot.sent) == alerts.MAX_PER_HOUR
    run(scenario)


def test_nothing_is_sent_without_an_owner(monkeypatch):
    async def scenario():
        monkeypatch.setattr(config, "ADMIN_IDS", set())
        bot = FakeBot()
        assert await alerts.fire(bot, alerts.DISK, "warn", "диск 81%") is False
        assert bot.sent == []
    run(scenario)


def test_one_failure_is_bad_luck_a_streak_is_a_breakdown():
    for _ in range(alerts.ERROR_THRESHOLD - 1):
        assert alerts.record_failure() is False
    assert alerts.record_failure() is True


def test_old_failures_do_not_count():
    """Пять сбоев за неделю — не поломка."""
    stale = datetime.now(timezone.utc) - alerts.ERROR_WINDOW - timedelta(minutes=1)
    for _ in range(alerts.ERROR_THRESHOLD):
        alerts._failures.append(stale)
    assert alerts.record_failure() is False


# --- Проверки состояния ------------------------------------------------

def test_disk_warning_then_all_clear(monkeypatch):
    """Диск заполняется, потом освобождается — два сообщения, не двадцать."""
    from services import guard
    from utils.disk import DiskUsage

    async def scenario():
        bot = FakeBot()
        state = {"percent": 85}

        monkeypatch.setattr(guard, "disk_usage", lambda: DiskUsage(
            total_gb=40, used_gb=40 * state["percent"] / 100,
            free_gb=40 - 40 * state["percent"] / 100, percent=state["percent"]))
        monkeypatch.setattr(config, "DISK_WARN_PERCENT", 80)
        monkeypatch.setattr(config, "DISK_STOP_PERCENT", 90)

        await guard.check_disk(bot)
        await guard.check_disk(bot)          # ничего не изменилось — молчим
        assert len(bot.sent) == 1
        assert "80" not in bot.sent[0][1] or "85" in bot.sent[0][1]

        state["percent"] = 92                # стало хуже — это новость
        await guard.check_disk(bot)
        assert len(bot.sent) == 2

        state["percent"] = 40                # отпустило
        await guard.check_disk(bot)
        assert len(bot.sent) == 3
        assert "нормально" in bot.sent[2][1]

        await guard.check_disk(bot)          # и снова тишина
        assert len(bot.sent) == 3
    run(scenario)


def test_alert_comes_with_a_command_to_run(monkeypatch):
    """Сигнал без готовой команды заставляет искать, что делать."""
    from services import guard
    from utils.disk import DiskUsage

    async def scenario():
        bot = FakeBot()
        monkeypatch.setattr(guard, "disk_usage",
                            lambda: DiskUsage(total_gb=40, used_gb=38, free_gb=2, percent=95))
        monkeypatch.setattr(config, "DISK_WARN_PERCENT", 80)
        monkeypatch.setattr(config, "DISK_STOP_PERCENT", 90)

        await guard.check_disk(bot)
        assert "du -sh" in bot.sent[0][1]
    run(scenario)


def test_a_broken_check_does_not_stop_the_others(monkeypatch):
    """Одна упавшая проверка не должна отменять остальные."""
    from services import guard

    calls = []

    async def boom(bot):
        raise RuntimeError("диск не читается")

    async def fine(bot):
        calls.append("ok")

    async def scenario():
        monkeypatch.setattr(guard, "check_disk", boom)
        monkeypatch.setattr(guard, "check_budget", fine)
        monkeypatch.setattr(guard, "check_spike", fine)
        await guard.watch(FakeBot())
        assert calls == ["ok", "ok"]
    run(scenario)
