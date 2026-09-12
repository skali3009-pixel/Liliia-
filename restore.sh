#!/usr/bin/env bash
# Восстановить бота из резервной копии.
#
#   bash restore.sh /root/nutrition-backups/aura-20260906-0430.tar.gz
#
# Скрипт останавливает бота, заменяет базу и фотографии данными из копии и
# запускает бота обратно. Текущая база перед этим сохраняется отдельным
# файлом — на случай, если восстановились не из той копии.
#
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="nutrition-bot"
ARCHIVE="${1:-}"

cd "$APP_DIR"
[ -f .env ] && set -a && . ./.env && set +a

log() { printf '%s %s\n' "$(date '+%d.%m %H:%M:%S')" "$*"; }
fail() { log "ОШИБКА: $*"; exit 1; }

[ -n "$ARCHIVE" ] || fail "укажи файл копии: bash restore.sh <файл.tar.gz>"
[ -f "$ARCHIVE" ] || fail "файл не найден: $ARCHIVE"

DB_URL="$(printf '%s' "${DATABASE_URL:-}" | sed 's|+asyncpg||')"
[ -n "$DB_URL" ] || fail "в .env нет DATABASE_URL"

echo
echo "Это заменит текущие данные бота данными из копии:"
echo "  $ARCHIVE"
echo
read -r -p "Продолжить? Напиши «да»: " ANSWER
[ "$ANSWER" = "да" ] || { echo "Отменено."; exit 0; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$ARCHIVE" -C "$TMP" || fail "не распаковать архив"
INNER="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)"
[ -f "$INNER/db.dump" ] || fail "в архиве нет db.dump"

log "Останавливаю бота…"
systemctl stop "$SERVICE" 2>/dev/null || true

SAFETY="/root/nutrition-backups/before-restore-$(date '+%Y%m%d-%H%M').dump"
mkdir -p "$(dirname "$SAFETY")"
log "Сохраняю текущую базу на всякий случай: $SAFETY"
pg_dump --format=custom --no-owner --no-privileges --file="$SAFETY" "$DB_URL" || \
  log "текущую базу сохранить не вышло — продолжаю"

log "Восстанавливаю базу…"
if ! pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$DB_URL" \
     "$INNER/db.dump"; then
  log "pg_restore сообщил об ошибках — проверь вывод выше"
fi

if [ -f "$INNER/photos.tar.gz" ]; then
  PHOTOS="${PHOTOS_DIR:-$APP_DIR/data/photos}"
  log "Возвращаю фотографии…"
  mkdir -p "$(dirname "$PHOTOS")"
  tar -xzf "$INNER/photos.tar.gz" -C "$(dirname "$PHOTOS")"
fi

log "Запускаю бота…"
systemctl start "$SERVICE" 2>/dev/null || true
sleep 5
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  log "Готово: бот работает на восстановленных данных"
else
  log "Бот не поднялся — посмотри: journalctl -u $SERVICE -n 50"
fi
