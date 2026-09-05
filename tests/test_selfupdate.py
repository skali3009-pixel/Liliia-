"""Тесты самообновления (services/selfupdate.py)."""

import asyncio

import pytest

from services import selfupdate
from services.selfupdate import UPDATE_UNIT, _launch_command, has_update, run_update


class _Git:
    """Подменяет вызовы команд: отвечает по первому подходящему шаблону."""

    def __init__(self, answers: dict[str, tuple[int, str]]):
        self.answers = answers
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *args: str, timeout: int = 0) -> tuple[int, str]:
        self.calls.append(args)
        line = " ".join(args)
        for pattern, answer in self.answers.items():
            if pattern in line:
                return answer
        return 0, ""


def setup_git(monkeypatch, answers):
    fake = _Git(answers)
    monkeypatch.setattr(selfupdate, "_run", fake)
    return fake


SAME = {
    "rev-parse --abbrev-ref": (0, "main"),
    "fetch": (0, ""),
    "rev-parse HEAD": (0, "abc123"),
    "rev-parse origin/main": (0, "abc123"),
}
NEWER = {**SAME, "rev-parse origin/main": (0, "def456")}


def test_no_update_when_commits_match(monkeypatch):
    setup_git(monkeypatch, SAME)
    assert asyncio.run(has_update()) is False


def test_update_is_seen_when_remote_moved(monkeypatch):
    setup_git(monkeypatch, NEWER)
    assert asyncio.run(has_update()) is True


def test_unreachable_git_is_not_an_update(monkeypatch):
    """Нет сети — просто ждём следующей проверки, ничего не трогаем."""
    setup_git(monkeypatch, {**NEWER, "fetch": (1, "не удалось подключиться")})
    assert asyncio.run(has_update()) is False


def test_nothing_runs_when_there_is_no_update(monkeypatch):
    fake = setup_git(monkeypatch, SAME)
    assert asyncio.run(run_update()) is False
    # update.sh даже не пытались запустить
    assert all("update.sh" not in " ".join(call) for call in fake.calls)


def test_update_script_is_launched_when_version_is_newer(monkeypatch):
    fake = setup_git(monkeypatch, NEWER)
    assert asyncio.run(run_update()) is True
    assert any("update.sh" in " ".join(call) for call in fake.calls)


def test_failed_launch_is_reported_not_raised(monkeypatch):
    setup_git(monkeypatch, {**NEWER, "update.sh": (1, "нет прав")})
    assert asyncio.run(run_update()) is False


def test_missing_script_is_survivable(monkeypatch, tmp_path):
    monkeypatch.setattr(selfupdate, "UPDATE_SCRIPT", tmp_path / "нет-такого.sh")
    assert asyncio.run(run_update()) is False


def test_update_runs_in_its_own_systemd_unit(monkeypatch):
    """Иначе перезапуск бота убил бы обновление до проверки и отката."""
    monkeypatch.setattr(selfupdate.shutil, "which", lambda name: f"/usr/bin/{name}")

    command = _launch_command()

    assert command[0] == "systemd-run"
    assert f"--unit={UPDATE_UNIT}" in command
    assert command[-2:] == ["/bin/bash", str(selfupdate.UPDATE_SCRIPT)]


def test_without_systemd_the_script_runs_directly(monkeypatch):
    monkeypatch.setattr(selfupdate.shutil, "which", lambda name: None)
    assert _launch_command() == ["/bin/bash", str(selfupdate.UPDATE_SCRIPT)]


@pytest.mark.parametrize("timeout_name", ["GIT_TIMEOUT", "LAUNCH_TIMEOUT"])
def test_timeouts_are_sane(timeout_name):
    """Проверка git и запуск обновления не должны висеть минутами."""
    assert 0 < getattr(selfupdate, timeout_name) <= 120
