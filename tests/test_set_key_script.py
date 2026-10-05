"""Run the key installer against a fake provider; never touch a real key/service."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


def installer(tmp_path, code, key, curl_exit=0):
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    bash = str(git_bash) if os.name == "nt" and git_bash.exists() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash is needed to exercise the installer")
    source = Path(__file__).resolve().parents[1] / "set-key.sh"
    (tmp_path / "set-key.sh").write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=old-test-value\nOTHER=keep\n", encoding="utf-8")
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    for name, content in {
        "curl": '#!/usr/bin/env bash\nprintf checked > "$PWD/provider-called"\nprintf "%s" "$TEST_HTTP_CODE"\nexit "$TEST_CURL_EXIT"\n',
        "systemctl": '#!/usr/bin/env bash\nprintf called > "$PWD/service-called"\nexit 1\n',
    }.items():
        target = bin_path / name
        target.write_text(content, encoding="utf-8", newline="\n")
        target.chmod(0o700)
    result = subprocess.run(
        [bash, "-c", 'export PATH="$PWD/bin:$PATH"; exec bash ./set-key.sh ANTHROPIC_API_KEY'],
        input=key + "\n", capture_output=True, text=True, encoding="utf-8", timeout=15,
        cwd=tmp_path, env={**os.environ, "TEST_HTTP_CODE": str(code), "TEST_CURL_EXIT": str(curl_exit)},
    )
    assert key not in result.stdout + result.stderr
    return result


@pytest.mark.parametrize("length", [76, 108])
def test_provider_accepted_keys_are_not_rejected_by_length(tmp_path, length):
    key = "sk-ant-api03-" + "a" * (length - len("sk-ant-api03-"))
    result = installer(tmp_path, 200, key)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / ".env").read_text() == f"OTHER=keep\nANTHROPIC_API_KEY={key}\n"
    assert (tmp_path / "provider-called").exists()


@pytest.mark.parametrize("code,curl_exit,length", [
    (401, 0, 76), (401, 0, 24), (400, 0, 76), (402, 0, 76),
    (403, 0, 76), (429, 0, 76), (500, 0, 76), ("000", 28, 76),
])
def test_unconfirmed_key_preserves_env_and_does_not_restart(tmp_path, code, curl_exit, length):
    key = "sk-ant-api03-" + "b" * (length - len("sk-ant-api03-"))
    result = installer(tmp_path, code, key, curl_exit)
    assert result.returncode != 0
    assert (tmp_path / ".env").read_text() == "ANTHROPIC_API_KEY=old-test-value\nOTHER=keep\n"
    assert (tmp_path / "provider-called").exists()
    assert not (tmp_path / "service-called").exists()
