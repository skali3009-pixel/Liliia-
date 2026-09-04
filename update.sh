#!/usr/bin/env bash
# Обновить бота до последней версии из git и перезапустить.
#
# Скрипт безопасен для автозапуска: если новая версия не поднялась, он
# возвращает предыдущую и перезапускает её. Лучше работать на старом коде,
# чем не работать на новом.
#
#   bash update.sh
#
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="nutrition-bot"
cd "$APP_DIR"

log() { printf '%s %s\n' "$(date '+%d.%m %H:%M:%S')" "$*"; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if ! git fetch --quiet origin "$BRANCH" 2>/dev/null; then
  log "Не удалось связаться с git — попробую в следующий раз."
  exit 0
fi

BEFORE="$(git rev-parse HEAD)"
AFTER="$(git rev-parse "origin/$BRANCH")"
if [ "$BEFORE" = "$AFTER" ]; then
  exit 0   # обновлений нет, тишина
fi

log "Обновление: ${BEFORE:0:7} → ${AFTER:0:7}"
# Локальных правок на сервере нет, поэтому просто встаём на версию из git.
git reset --hard --quiet "$AFTER"

# Зависимости ставим, только если список изменился: это долго.
if ! git diff --quiet "$BEFORE" "$AFTER" -- requirements.txt; then
  log "Обновляю зависимости"
  "$APP_DIR/.venv/bin/pip" install --quiet --upgrade -r "$APP_DIR/requirements.txt"
fi

systemctl restart "$SERVICE"
sleep 8

if systemctl is-active --quiet "$SERVICE"; then
  log "Готово, бот работает на ${AFTER:0:7}"
  exit 0
fi

log "Новая версия не поднялась — откатываюсь на ${BEFORE:0:7}"
git reset --hard --quiet "$BEFORE"
systemctl restart "$SERVICE"
sleep 5
if systemctl is-active --quiet "$SERVICE"; then
  log "Откат удался, бот работает на прежней версии"
else
  log "Бот не поднимается и после отката — смотри journalctl -u $SERVICE"
fi
exit 1
