#!/usr/bin/env bash
# Указать владельца бота: кому приходят отчёты и кто управляет доступом.
#
#   bash set-admin.sh 123456789          — один владелец
#   bash set-admin.sh 123456789,987654   — несколько
#   bash set-admin.sh                    — показать текущих
#
# Свой номер можно узнать у самого бота: напиши ему /id
#
# Без этой настройки платный доступ выключен (бот бесплатен для всех), а
# отчёты о расходах и предупреждения о сбоях отправлять некому.
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
SERVICE="nutrition-bot"
IDS="${1:-}"

[ -f "$ENV_FILE" ] || { echo "Не нашёл $ENV_FILE — бот точно установлен?"; exit 1; }

current="$(grep -E '^ADMIN_IDS=' "$ENV_FILE" | cut -d= -f2- || true)"

# Показать, кто владелец, и заодно первых людей из базы: свой номер проще
# всего узнать здесь же, не переписываясь с ботом и не ставя посторонних.
list_people() {
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
  local url="${DATABASE_URL/+asyncpg/}"
  [ -n "$url" ] || return 0

  echo
  echo "Первые, кто зашёл в бота (ты почти наверняка первая строка):"
  psql "$url" -P pager=off -c \
    "SELECT id AS номер, coalesce(full_name, '—') AS имя,
            created_at::date AS пришёл
       FROM users ORDER BY created_at LIMIT 10" 2>/dev/null \
    || echo "  (не удалось прочитать базу — проверь DATABASE_URL в .env)"
}

if [ -z "$IDS" ]; then
  if [ -n "$current" ]; then
    echo "Сейчас владельцы: $current"
  else
    echo "Владелец не задан. Из-за этого:"
    echo "  • платный доступ выключен — бот бесплатен для всех;"
    echo "  • отчёты о расходах и предупреждения о сбоях отправлять некому."
  fi
  list_people
  echo
  echo "Записать владельца: bash set-admin.sh <номер>"
  exit 0
fi

# Только цифры и запятые: чужой мусор в этой строке ломает запуск бота.
if ! printf '%s' "$IDS" | grep -qE '^[0-9]+(,[0-9]+)*$'; then
  echo "Номер — это цифры (можно несколько через запятую). Получено: $IDS"
  exit 1
fi

if grep -qE '^ADMIN_IDS=' "$ENV_FILE"; then
  sed -i "s|^ADMIN_IDS=.*|ADMIN_IDS=$IDS|" "$ENV_FILE"
else
  printf 'ADMIN_IDS=%s\n' "$IDS" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

echo "Владельцы записаны: $IDS"
systemctl restart "$SERVICE" 2>/dev/null || true
sleep 5
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  echo "Бот перезапущен. Напиши ему /id — он подтвердит, что видит тебя владельцем."
  echo "Проверить остальное: bash status.sh"
else
  echo "Бот не поднялся — посмотри: journalctl -u $SERVICE -n 50"
fi
