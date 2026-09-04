"""Тесты самообновления (services/selfupdate.py)."""

import asyncio

from services import selfupdate
from services.selfupdate import run_update


def make_script(tmp_path, body: str):
    """Подменить update.sh на игрушечный и вернуть путь к нему."""
    script = tmp_path / "update.sh"
    script.write_text(f"#!/usr/bin/env bash\n{body}\n")
    script.chmod(0o755)
    return script


def test_silent_script_means_no_update(monkeypatch, tmp_path):
    """Когда обновлять нечего, скрипт молчит — и в лог ничего не идёт."""
    monkeypatch.setattr(selfupdate, "UPDATE_SCRIPT", make_script(tmp_path, "exit 0"))
    monkeypatch.setattr(selfupdate, "APP_DIR", tmp_path)

    assert asyncio.run(run_update()) is False


def test_output_means_something_happened(monkeypatch, tmp_path):
    monkeypatch.setattr(selfupdate, "UPDATE_SCRIPT",
                        make_script(tmp_path, "echo 'Обновление: aaa → bbb'"))
    monkeypatch.setattr(selfupdate, "APP_DIR", tmp_path)

    assert asyncio.run(run_update()) is True


def test_failing_script_does_not_raise(monkeypatch, tmp_path):
    """Упавшее обновление — это запись в логе, а не падение бота."""
    monkeypatch.setattr(selfupdate, "UPDATE_SCRIPT",
                        make_script(tmp_path, "echo 'откат'; exit 1"))
    monkeypatch.setattr(selfupdate, "APP_DIR", tmp_path)

    assert asyncio.run(run_update()) is True


def test_missing_script_is_survivable(monkeypatch, tmp_path):
    monkeypatch.setattr(selfupdate, "UPDATE_SCRIPT", tmp_path / "нет-такого.sh")

    assert asyncio.run(run_update()) is False


def test_hanging_script_is_cut_off(monkeypatch, tmp_path):
    """Зависшее обновление не должно висеть вечно."""
    monkeypatch.setattr(selfupdate, "UPDATE_SCRIPT", make_script(tmp_path, "sleep 30"))
    monkeypatch.setattr(selfupdate, "APP_DIR", tmp_path)
    monkeypatch.setattr(selfupdate, "TIMEOUT_SECONDS", 1)

    assert asyncio.run(run_update()) is False
