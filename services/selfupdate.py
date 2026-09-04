"""Самообновление: бот сам подтягивает новые версии и перезапускается.

Обновлять сервер руками неудобно, а забытое обновление — это старые ошибки
и невидимые новые разделы. Поэтому раз в полчаса бот запускает update.sh:
тот проверяет git, обновляется и, если новая версия не поднялась,
возвращает предыдущую.

Выключается переменной AUTO_UPDATE=0 в .env.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
UPDATE_SCRIPT = APP_DIR / "update.sh"

# Обновление длится дольше обычной команды: установка зависимостей и
# перезапуск сервиса с проверкой. Больше десяти минут — что-то не так.
TIMEOUT_SECONDS = 600


async def run_update() -> bool:
    """Проверить обновления и применить их. True — если что-то изменилось."""
    if not UPDATE_SCRIPT.exists():
        logger.warning("Нет %s — автообновление пропущено", UPDATE_SCRIPT.name)
        return False

    try:
        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            str(UPDATE_SCRIPT),
            cwd=str(APP_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.error("Автообновление зависло дольше %d с", TIMEOUT_SECONDS)
        return False
    except OSError as e:
        logger.warning("Автообновление не запустилось: %s", e)
        return False

    output = stdout.decode("utf-8", "replace").strip()
    if output:
        # Скрипт молчит, когда обновлять нечего, — в лог попадает только дело.
        logger.info("Автообновление:\n%s", output)

    # Обновившись, бот перезапускается силами systemd и сюда уже не вернётся.
    return bool(output)
