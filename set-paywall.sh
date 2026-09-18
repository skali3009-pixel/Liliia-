#!/usr/bin/env bash
# Платный доступ: включить или выключить.
#
#   bash set-paywall.sh          — показать, как сейчас
#   bash set-paywall.sh off      — бот бесплатный для всех
#   bash set-paywall.sh on       — доступ по подписке
#
# Пока бот дорабатывается, он должен быть бесплатным: люди приходят, пробуют,
# и закрывать им доступ на полпути нечестно. Поэтому оплата включается только
# этой командой и никогда сама собой.
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
SERVICE="nutrition-bot"
MODE="${1:-}"

[ -f "$ENV_FILE" ] || { echo "Не нашёл $ENV_FILE — бот точно установлен?"; exit 1; }

value() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

PAYWALL="$(value PAYWALL)"
OWNER="$(value ADMIN_IDS)"

show() {
  case "${PAYWALL,,}" in
    1|true|yes|on)
      if [ -n "$OWNER" ]; then
        echo "Сейчас: 🔒 доступ по подписке."
      else
        # Без владельца бот всё равно открыт: иначе некому чинить и выдавать доступ.
        echo "Сейчас: 🔓 бесплатно для всех — в .env стоит PAYWALL=1, но пуст ADMIN_IDS."
        echo "Кто владелец, задаётся так: bash set-admin.sh <номер>"
      fi
      ;;
    *) echo "Сейчас: 🔓 бот бесплатный для всех." ;;
  esac
}

if [ -z "$MODE" ]; then
  show
  echo
  echo "Включить оплату:  bash set-paywall.sh on"
  echo "Выключить:        bash set-paywall.sh off"
  exit 0
fi

case "${MODE,,}" in
  on|вкл|1)  NEW=1 ;;
  off|выкл|0) NEW=0 ;;
  *) echo "Понимаю только: on или off. Получено: $MODE"; exit 1 ;;
esac

if [ "$NEW" = "1" ] && [ -z "$OWNER" ]; then
  echo "Сначала нужен владелец, иначе бот закроется и от тебя тоже:"
  echo "  bash set-admin.sh <твой номер>"
  exit 1
fi

if grep -qE '^PAYWALL=' "$ENV_FILE"; then
  sed -i "s|^PAYWALL=.*|PAYWALL=$NEW|" "$ENV_FILE"
else
  printf 'PAYWALL=%s\n' "$NEW" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

if [ "$NEW" = "1" ]; then
  echo "Платный доступ ВКЛЮЧЁН."
  echo
  # Главное, о чём легко забыть: люди, которые уже пользуются ботом, упрутся
  # в оплату при следующем сообщении. Это решение владельца, а не побочный эффект.
  echo "Важно: те, кто уже пользуется ботом, при следующем сообщении увидят"
  echo "экран оплаты. Если кому-то из них доступ надо оставить бесплатным —"
  echo "  в боте: /grant <номер> навсегда"
  echo "  список людей: bash set-admin.sh"
else
  echo "Платный доступ ВЫКЛЮЧЕН — бот бесплатный для всех."
fi

systemctl restart "$SERVICE" 2>/dev/null || true
sleep 5
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  echo "Бот перезапущен. Проверить целиком: bash status.sh"
else
  echo "Бот не поднялся — посмотри: journalctl -u $SERVICE -n 50"
fi
