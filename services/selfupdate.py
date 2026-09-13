"""Самообновление: бот сам подтягивает новые версии и перезапускается.

Обновлять сервер руками неудобно, а забытое обновление — это старые ошибки
и невидимые новые разделы. Поэтому бот раз в полчаса заглядывает в git и,
если появилась новая версия, запускает update.sh.

Тонкость: update.sh перезапускает сам сервис бота. Запущенный как обычный
дочерний процесс, он был бы убит вместе с ботом на середине — как раз перед
проверкой «поднялось ли» и откатом. Поэтому обновление уводится в отдельную
единицу systemd, которая переживает перезапуск бота.

Выключается переменной AUTO_UPDATE=0 в .env.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
UPDATE_SCRIPT = APP_DIR / "update.sh"

# Имя единицы, в которой идёт обновление. Логи: journalctl -u <имя>.
UPDATE_UNIT = "nutrition-bot-selfupdate"

GIT_TIMEOUT = 60
LAUNCH_TIMEOUT = 30


async def _run(*args: str, timeout: int) -> tuple[int, str]:
    """Выполнить команду в каталоге проекта. Возвращает (код, вывод)."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(APP_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Команда %s не уложилась в %d с", args[0], timeout)
        return 1, ""
    except OSError as e:
        logger.warning("Команда %s не запустилась: %s", args[0], e)
        return 1, ""

    return process.returncode or 0, stdout.decode("utf-8", "replace").strip()


async def has_update() -> bool:
    """Появилась ли в git версия новее той, на которой работаем."""
    code, branch = await _run("git", "rev-parse", "--abbrev-ref", "HEAD", timeout=GIT_TIMEOUT)
    if code or not branch:
        return False

    code, _ = await _run("git", "fetch", "--quiet", "origin", branch, timeout=GIT_TIMEOUT)
    if code:
        logger.debug("Не удалось связаться с git — проверю в следующий раз")
        return False

    _, local = await _run("git", "rev-parse", "HEAD", timeout=GIT_TIMEOUT)
    code, remote = await _run("git", "rev-parse", f"origin/{branch}", timeout=GIT_TIMEOUT)
    if code or not remote:
        return False

    return bool(local) and local != remote


def _launch_command() -> list[str]:
    """Чем запускать обновление.

    systemd-run уносит скрипт в собственную единицу: перезапуск бота её не
    трогает, и откат при неудаче успевает отработать. Без systemd (например,
    при запуске из консоли) остаётся обычный вызов.
    """
    if shutil.which("systemd-run"):
        return [
            "systemd-run",
            "--collect",       # убрать единицу после завершения
            "--quiet",
            f"--unit={UPDATE_UNIT}",
            # Каталог не указываем: update.sh сам переходит в свою папку,
            # а лишний флаг — лишний повод для systemd отказаться запускать.
            "/bin/bash",
            str(UPDATE_SCRIPT),
        ]
    return ["/bin/bash", str(UPDATE_SCRIPT)]


async def run_update() -> bool:
    """Проверить обновления и запустить их. True — если обновление пошло."""
    if not UPDATE_SCRIPT.exists():
        logger.warning("Нет %s — автообновление пропущено", UPDATE_SCRIPT.name)
        return False

    if not await has_update():
        return False

    logger.info("Есть новая версия — обновляюсь (логи: journalctl -u %s)", UPDATE_UNIT)
    code, output = await _run(*_launch_command(), timeout=LAUNCH_TIMEOUT)
    if code:
        logger.error("Обновление не запустилось: %s", output or f"код {code}")
        return False

    # Дальше бота перезапустит update.sh, и этот процесс просто закончится.
    return True
