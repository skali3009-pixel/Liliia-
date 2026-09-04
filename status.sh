#!/usr/bin/env bash
# Что сейчас с ботом: открыт он всем или закрыт, сколько людей, всё ли готово.
#
#   bash status.sh
#
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

cd "$DIR"
set -a; [ -f .env ] && . ./.env; set +a

if systemctl is-active --quiet nutrition-bot 2>/dev/null; then
  echo "🤖 Бот: работает"
else
  echo "🤖 Бот: НЕ РАБОТАЕТ — journalctl -u nutrition-bot -n 30"
fi
echo

"$PYTHON" -m services.status
