#!/usr/bin/env bash
# Досоздать то, без чего бот работает, но остаётся без присмотра: сторожа,
# ночные копии и автообновление.
#
#   bash ensure-ops.sh          — доставить недостающее
#   bash ensure-ops.sh --check  — только показать, что есть и чего нет
#
# Зачем это отдельно от install.sh: бот, поставленный раньше, обо всём этом
# не знает, а владелец не обязан ходить по консоли и вспоминать, какие
# команды он ещё не запускал. Скрипт вызывается из update.sh, то есть
# доезжает до сервера сам, вместе с обновлением.
#
# Правила: ничего не переустанавливать, если уже стоит; никогда не мешать
# обновлению — что бы здесь ни сломалось, бот должен подняться.
#
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
[ -f .env ] && set -a && . ./.env && set +a

log() { printf '%s %s\n' "$(date '+%d.%m %H:%M:%S')" "$*"; }

# Сообщение владельцу идёт напрямую через Телеграм: бот в этот момент как
# раз перезапускается и передать через него ничего нельзя.
tell_owner() {
  local who
  who="$(printf '%s' "${ADMIN_IDS:-}" | cut -d, -f1 | tr -d ' ')"
  [ -n "$who" ] && [ -n "${BOT_TOKEN:-}" ] || return 0
  curl -sS -m 30 -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
    -d "chat_id=$who" --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

# Таймер считается на месте, только если он и включён, и заведён в systemd.
have() { systemctl is-enabled --quiet "$1.timer" 2>/dev/null; }

WATCHDOG="nutrition-bot-watchdog"
BACKUP="nutrition-bot-backup"
UPDATER="nutrition-bot-update"

if [ "${1:-}" = "--check" ]; then
  for unit in "$WATCHDOG:сторож" "$BACKUP:ночные копии" "$UPDATER:автообновление"; do
    name="${unit%%:*}"; title="${unit#*:}"
    if have "$name"; then echo "✅ $title"; else echo "❌ $title — не включено"; fi
  done
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  # Не ошибка: значит, бот работает не от root и таймеры ставятся вручную.
  log "Не root — пропускаю установку служб"
  exit 0
fi

ADDED=()

if ! have "$WATCHDOG"; then
  if bash "$APP_DIR/setup-watchdog.sh" >/dev/null 2>&1; then
    ADDED+=("🐕 Сторож — проверяет каждые 5 минут, жив ли бот")
    log "Сторож включён"
    # Сразу проверяем, что сообщение действительно доходит: сторож, о котором
    # неизвестно, работает ли он, — хуже, чем никакого.
    bash "$APP_DIR/watchdog.sh" --test >/dev/null 2>&1 || true
  else
    log "Не удалось включить сторожа"
  fi
fi

if ! have "$BACKUP"; then
  if bash "$APP_DIR/setup-backup.sh" >/dev/null 2>&1; then
    ADDED+=("🗄 Ночные копии — каждую ночь в 04:30, файл приходит сюда")
    log "Резервное копирование включено"
  else
    log "Не удалось включить резервное копирование"
  fi
fi

if ! have "$UPDATER"; then
  if bash "$APP_DIR/autoupdate.sh" >/dev/null 2>&1; then
    ADDED+=("🔄 Автообновление — сервер сам подтягивает новые версии")
    log "Автообновление включено"
  fi
fi

if [ ${#ADDED[@]} -gt 0 ]; then
  tell_owner "⚙️ Настроила на сервере то, что оставалось незапущенным:

$(printf '%s\n' "${ADDED[@]}")

Ничего делать не нужно, всё уже работает.
Проверить целиком: bash status.sh"
  log "Доставлено: ${#ADDED[@]}"
else
  log "Всё уже на месте"
fi

exit 0
