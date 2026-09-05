#!/usr/bin/env bash
# Скачать фоновые арты приложения вручную.
#
# Обычно этого делать не нужно: бот докачивает недостающие картинки сам при
# запуске. Скрипт нужен, только чтобы обновить арты, не перезапуская бота.
#
#   bash fetch-art.sh
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

cd "$DIR"
"$PYTHON" -m services.artwork
