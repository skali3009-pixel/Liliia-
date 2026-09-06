#!/usr/bin/env bash
# Сторож: замечает, что бот лёг, и пишет владельцу.
#
#   bash watchdog.sh          — одна проверка (запускается по таймеру)
#   bash watchdog.sh --test   — проверить, что сообщение доходит
#
# Главное здесь: сообщение отправляется напрямую в Телеграм через curl, а не
# через бота. Упавший бот не может пожаловаться на то, что он упал — именно
# поэтому такие вещи и остаются незамеченными сутками.
#
# Сторож не «чинит»: перезапуском занимается systemd. Его дело — чтобы
# владелец узнал.
#
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="nutrition-bot"
STATE_DIR="/var/lib/nutrition-bot"
STATE="$STATE_DIR/watchdog.state"
# Молчим первые две неудачи подряд: перезапуск после обновления занимает
# секунды, и поднимать тревогу из-за него незачем.
FAILS_BEFORE_ALERT=2
# Не повторяем тревогу чаще раза в час, чтобы не превратить её в спам.
REPEAT_AFTER=3600

cd "$APP_DIR"
[ -f .env ] && set -a && . ./.env && set +a

OWNER="$(printf '%s' "${ADMIN_IDS:-}" | cut -d, -f1 | tr -d ' ')"

notify() {
  [ -n "${BOT_TOKEN:-}" ] && [ -n "$OWNER" ] || return 0
  curl -sS -m 20 -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
    -d "chat_id=$OWNER" --data-urlencode "text=$1" >/dev/null 2>&1
}

if [ "${1:-}" = "--test" ]; then
  if [ -z "$OWNER" ]; then
    echo "ADMIN_IDS не задан — сторожу некому писать. Выполни: bash set-admin.sh <номер>"
    exit 1
  fi
  if notify "🐕 Сторож на связи. Если бот когда-нибудь ляжет, сообщение придёт сюда."; then
    echo "Отправлено владельцу $OWNER — проверь чат с ботом."
  else
    echo "Отправить не удалось. Проверь BOT_TOKEN в .env."
  fi
  exit 0
fi

mkdir -p "$STATE_DIR" 2>/dev/null || true
FAILS=0
LAST_ALERT=0
if [ -f "$STATE" ]; then
  # shellcheck disable=SC1090
  . "$STATE"
fi

# --- Собственно проверка ---------------------------------------------------
PROBLEM=""

if ! systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  PROBLEM="служба $SERVICE не работает"
else
  # Служба может «работать», но крутиться в цикле перезапусков: снаружи это
  # выглядит как живой бот, а на деле он не отвечает.
  RESTARTS="$(systemctl show "$SERVICE" -p NRestarts --value 2>/dev/null || echo 0)"
  PREV_RESTARTS="${PREV_RESTARTS:-$RESTARTS}"
  if [ "$RESTARTS" -gt "$((PREV_RESTARTS + 3))" ]; then
    PROBLEM="бот перезапускается по кругу (${RESTARTS} раз)"
  fi

  # Мини-приложение отвечает на /health — это проверка, что процесс живой,
  # а не просто числится запущенным.
  PORT="${WEBAPP_PORT:-8080}"
  HOST="${WEBAPP_HOST:-127.0.0.1}"
  if ! curl -sS -m 10 -o /dev/null "http://$HOST:$PORT/health" 2>/dev/null; then
    PROBLEM="${PROBLEM:+$PROBLEM; }приложение не отвечает на $HOST:$PORT"
  fi
fi

NOW="$(date +%s)"

if [ -z "$PROBLEM" ]; then
  if [ "$FAILS" -ge "$FAILS_BEFORE_ALERT" ]; then
    notify "✅ Бот снова работает. Был недоступен с $(date -d "@$LAST_ALERT" '+%d.%m %H:%M')."
  fi
  printf 'FAILS=0\nLAST_ALERT=0\nPREV_RESTARTS=%s\n' "${RESTARTS:-0}" > "$STATE"
  exit 0
fi

FAILS=$((FAILS + 1))
printf 'FAILS=%s\nLAST_ALERT=%s\nPREV_RESTARTS=%s\n' \
  "$FAILS" "$LAST_ALERT" "${PREV_RESTARTS:-0}" > "$STATE"

if [ "$FAILS" -lt "$FAILS_BEFORE_ALERT" ]; then
  exit 0   # первая неудача — скорее всего, обычный перезапуск
fi
if [ "$LAST_ALERT" -ne 0 ] && [ "$((NOW - LAST_ALERT))" -lt "$REPEAT_AFTER" ]; then
  exit 0   # уже сообщали недавно
fi

LOG="$(journalctl -u "$SERVICE" -n 12 --no-pager 2>/dev/null | tail -8)"
notify "🛑 Бот не работает: $PROBLEM

Последние строки журнала:
$LOG

На сервере: systemctl status $SERVICE"

printf 'FAILS=%s\nLAST_ALERT=%s\nPREV_RESTARTS=%s\n' \
  "$FAILS" "$NOW" "${PREV_RESTARTS:-0}" > "$STATE"
