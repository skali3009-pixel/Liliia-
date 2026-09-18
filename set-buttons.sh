#!/usr/bin/env bash
# Счёт нажатий кнопок меню в чате: включить или выключить.
#
#   bash set-buttons.sh          — показать, как сейчас
#   bash set-buttons.sh off      — перестать считать
#   bash set-buttons.sh on       — считать снова
#
# Счёт заведён на время испытаний: без него «этой кнопкой не пользуются» —
# догадка одного человека, а не факт. Когда решение по кнопкам принято,
# счётчик надо выключить: забытый, он тихо растит таблицу и остаётся в
# коде навсегда.
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
SERVICE="nutrition-bot"
MODE="${1:-}"

[ -f "$ENV_FILE" ] || { echo "Не нашёл $ENV_FILE — бот точно установлен?"; exit 1; }

value() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

show() {
  case "$(value BUTTON_STATS | tr '[:upper:]' '[:lower:]')" in
    0|false|no|off) echo "Сейчас: нажатия НЕ считаются." ;;
    *)              echo "Сейчас: нажатия считаются. Итоги — в /status и в недельном отчёте." ;;
  esac
}

set_value() {
  if grep -qE '^BUTTON_STATS=' "$ENV_FILE"; then
    sed -i "s/^BUTTON_STATS=.*/BUTTON_STATS=$1/" "$ENV_FILE"
  else
    printf 'BUTTON_STATS=%s\n' "$1" >> "$ENV_FILE"
  fi
  systemctl restart "$SERVICE" 2>/dev/null || true
}

case "${MODE,,}" in
  on)  set_value 1; echo "Готово: считаю нажатия." ;;
  off) set_value 0; echo "Готово: больше не считаю. Уже собранное остаётся в базе." ;;
  "")  show; echo; echo "Изменить: bash set-buttons.sh on | off" ;;
  *)   echo "Не понял «$MODE». Нужно on или off."; exit 1 ;;
esac
