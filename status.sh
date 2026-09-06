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

# --- Резервные копии -------------------------------------------------------
echo
echo "Резервные копии:"
BACKUP_DIR="${BACKUP_DIR:-/root/nutrition-backups}"
LAST="$(ls -1t "$BACKUP_DIR"/aura-*.tar.gz 2>/dev/null | head -1)"
if [ -n "$LAST" ]; then
  echo "  последняя: $(date -r "$LAST" '+%d.%m.%Y %H:%M') "\
       "($(( $(stat -c %s "$LAST") / 1024 / 1024 )) МБ)"
  echo "  всего на диске: $(ls -1 "$BACKUP_DIR"/aura-*.tar.gz 2>/dev/null | wc -l)"
else
  echo "  копий нет — включи: sudo bash setup-backup.sh"
fi
if systemctl is-enabled --quiet nutrition-bot-backup.timer 2>/dev/null; then
  echo "  расписание: включено, следующая — $(systemctl show nutrition-bot-backup.timer \
       -p NextElapseUSecRealtime --value 2>/dev/null | cut -c1-16)"
else
  echo "  расписание: выключено (sudo bash setup-backup.sh)"
fi
