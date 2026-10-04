"""Доступ Тимура к серверу (grant-timur.sh).

Скрипт запускается от root на живом сервере, где лежат база, копии и
другие боты. Поэтому сторожим то, что нельзя увидеть по зелёному итогу:
скрипт не трогает ни настройки SSH, ни ключи root, не открывает проход
через /root и не выдаёт sudo шире четырёх своих команд.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "grant-timur.sh"
KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHyuTu+vzFcoIAs8DWsg9bGN0eqd0Oqxj1"
       "+L658Voiw8 aura-timur-20261004")


def code() -> str:
    """Исполняемые строки — без комментариев: в них запреты названы по делу."""
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


@pytest.mark.skipif(shutil.which("bash") is None, reason="нет bash")
def test_the_script_is_valid_bash():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_the_key_is_timurs_and_written_once():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.count(KEY) == 1
    # Повторный запуск не дублирует ключ: перед добавлением ищется его тело.
    assert 'grep -qF "$KEY_BODY" "$AUTH"' in text


def test_ssh_settings_and_root_keys_are_left_alone():
    body = code()
    assert not re.search(r">>?\s*\S*/etc/ssh", body)
    assert "sshd_config" not in body
    assert not re.search(r"(sed|tee|>>?)[^\n]*/root/\.ssh", body)
    assert "systemctl restart ssh" not in body and "systemctl reload ssh" not in body


def test_no_way_through_root_and_no_open_permissions():
    body = code()
    assert "setfacl" not in body, "проход через /root открыл бы копии базы"
    assert not re.search(r"chmod\s+[0-7]*7[0-7]?\b", body)
    assert "chmod -R" not in body and "chown -R" not in body


def test_sudo_allows_only_the_four_tools():
    body = code()
    assert "NOPASSWD: AURA_" in body
    assert "NOPASSWD: ALL" not in body and "ALL=(ALL" not in body
    assert "visudo -cf" in body, "правило без проверки может сломать sudo целиком"
    assert re.search(r"TOOLS=\(aura-service aura-logs aura-run aura-git\)", body)


def test_owner_decisions_are_not_runnable():
    allowed = re.search(r'^SCRIPTS="([^"]+)"', code(), re.M).group(1).split()
    for name in ("set-admin", "set-legal", "set-paywall", "restore", "install"):
        assert name not in allowed
    for name in allowed:
        assert (ROOT / f"{name}.sh").exists(), name


def test_the_tools_check_their_arguments():
    body = code()
    # Скрипт по имени из списка, а не по пути.
    assert '[[ "\\$name" =~ ^[a-z-]{1,30}\\$ ]]' in body
    # У журнала и git нет просмотрщика: из него выходят в оболочку от root.
    assert body.count("SYSTEMD_PAGER=cat") >= 2
    assert "GIT_PAGER=cat" in body
    assert "exec journalctl --no-pager" in body
