#!/usr/bin/env bash
# Резервная копия бота: база и фотографии.
#
#   bash backup.sh            — сделать копию
#   bash backup.sh --now      — то же самое, но с подробным выводом
#
# Копия кладётся на диск и, если задан ADMIN_IDS, отправляется владельцу
# в Телеграм. Это не прихоть: копия на том же сервере не спасает, если
# умирает сам сервер. В переписке файл лежит вечно, ничего не стоит и
# достаётся с любого устройства.
#
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/root/nutrition-backups}"
KEEP_DAILY=7        # ежедневные копии за последнюю неделю
KEEP_WEEKLY=8       # плюс по одной копии в неделю за два месяца
TG_LIMIT=$((45 * 1024 * 1024))   # у ботов предел 50 МБ, берём с запасом

cd "$APP_DIR"
[ -f .env ] && set -a && . ./.env && set +a

log() { printf '%s %s\n' "$(date '+%d.%m %H:%M:%S')" "$*"; }

# Сказать владельцу напрямую через Телеграм, минуя бота: копия делается по
# расписанию ночью, и молча провалившийся бэкап обнаруживается ровно тогда,
# когда он был нужен, — то есть слишком поздно.
tell_owner() {
  local who
  who="$(printf '%s' "${ADMIN_IDS:-}" | cut -d, -f1 | tr -d ' ')"
  [ -n "$who" ] && [ -n "${BOT_TOKEN:-}" ] || return 0
  curl -sS -m 30 -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
    -d "chat_id=$who" --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

fail() {
  log "ОШИБКА: $*"
  tell_owner "🛑 Резервная копия не сделалась: $*

Данные целы, но новой копии за $(date '+%d.%m') нет. Проверить вручную:
bash backup.sh --now"
  exit 1
}

mkdir -p "$BACKUP_DIR" || fail "не создать $BACKUP_DIR"
STAMP="$(date '+%Y%m%d-%H%M')"
NAME="aura-$STAMP"
WORK="$BACKUP_DIR/$NAME"
mkdir -p "$WORK"

# --- База ------------------------------------------------------------------
# DATABASE_URL вида postgresql+asyncpg://user:pass@host:port/db — pg_dump
# понимает только postgresql://, поэтому приводим к нему.
DB_URL="$(printf '%s' "${DATABASE_URL:-}" | sed 's|+asyncpg||')"
[ -n "$DB_URL" ] || fail "в .env нет DATABASE_URL"

log "Выгружаю базу…"
if ! pg_dump --format=custom --no-owner --no-privileges --file="$WORK/db.dump" "$DB_URL"; then
  rm -rf "$WORK"
  fail "pg_dump не отработал — база не скопирована"
fi

# --- Фотографии ------------------------------------------------------------
PHOTOS="${PHOTOS_DIR:-$APP_DIR/data/photos}"
if [ -d "$PHOTOS" ] && [ -n "$(ls -A "$PHOTOS" 2>/dev/null)" ]; then
  log "Упаковываю фотографии…"
  tar -czf "$WORK/photos.tar.gz" -C "$(dirname "$PHOTOS")" "$(basename "$PHOTOS")" 2>/dev/null
fi

# --- Что внутри ------------------------------------------------------------
{
  echo "Копия AURA от $(date '+%d.%m.%Y %H:%M')"
  echo "Версия кода: $(git rev-parse --short HEAD 2>/dev/null || echo неизвестна)"
  echo
  echo "db.dump      — база целиком (pg_dump, формат custom)"
  echo "photos.tar.gz — фотографии прогресса"
  echo
  echo "Как восстановить: положить архив на сервер и выполнить"
  echo "  bash restore.sh <файл>"
} > "$WORK/ЧТО-ВНУТРИ.txt"

ARCHIVE="$BACKUP_DIR/$NAME.tar.gz"
tar -czf "$ARCHIVE" -C "$BACKUP_DIR" "$NAME" || fail "не собрать архив"
rm -rf "$WORK"
SIZE=$(stat -c %s "$ARCHIVE")
log "Копия готова: $ARCHIVE ($((SIZE / 1024 / 1024)) МБ)"

# --- Отправка владельцу ----------------------------------------------------
OWNER="$(printf '%s' "${ADMIN_IDS:-}" | cut -d, -f1 | tr -d ' ')"
if [ -n "$OWNER" ] && [ -n "${BOT_TOKEN:-}" ]; then
  if [ "$SIZE" -gt "$TG_LIMIT" ]; then
    log "Копия больше 45 МБ — в Телеграм не отправляю, она осталась на диске"
    curl -sS -m 30 -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
      -d "chat_id=$OWNER" \
      --data-urlencode "text=⚠️ Копия за $(date '+%d.%m') весит $((SIZE / 1024 / 1024)) МБ и не помещается в сообщение. Она лежит на сервере: $ARCHIVE" \
      >/dev/null || true
  else
    log "Отправляю копию владельцу…"
    if curl -sS -m 120 -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendDocument" \
        -F "chat_id=$OWNER" \
        -F "document=@$ARCHIVE" \
        -F "caption=🗄 Копия AURA от $(date '+%d.%m.%Y'). Сохрани её — по ней восстанавливается всё." \
        | grep -q '"ok":true'; then
      log "Отправлено"
    else
      log "Отправить не удалось — копия осталась на диске"
    fi
  fi
else
  log "ADMIN_IDS не задан — копия только на диске"
fi

# --- Ротация ---------------------------------------------------------------
# Оставляем последние копии за неделю и по одной в неделю за два месяца.
mapfile -t ALL < <(ls -1t "$BACKUP_DIR"/aura-*.tar.gz 2>/dev/null)
KEPT=0
declare -A WEEKS
for file in "${ALL[@]}"; do
  KEPT=$((KEPT + 1))
  [ "$KEPT" -le "$KEEP_DAILY" ] && continue
  WEEK="$(date -r "$file" '+%G-%V')"
  if [ -z "${WEEKS[$WEEK]:-}" ] && [ "${#WEEKS[@]}" -lt "$KEEP_WEEKLY" ]; then
    WEEKS[$WEEK]=1
    continue
  fi
  rm -f "$file"
done

log "На диске копий: $(ls -1 "$BACKUP_DIR"/aura-*.tar.gz 2>/dev/null | wc -l)"
