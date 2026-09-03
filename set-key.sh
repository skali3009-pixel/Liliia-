#!/usr/bin/env bash
# Добавить или заменить ключ в .env и перезапустить бота.
#
#   bash set-key.sh ANTHROPIC_API_KEY sk-ant-api03-...
#   bash set-key.sh VOICE_API_KEY gsk_...

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
NAME="${1:-}"
VALUE="${2:-}"

if [ -z "$NAME" ] || [ -z "$VALUE" ]; then
    echo "Как пользоваться:"
    echo "  bash set-key.sh ANTHROPIC_API_KEY sk-ant-api03-...   — распознавание фото"
    echo "  bash set-key.sh VOICE_API_KEY gsk_...                — голосовые сообщения"
    exit 1
fi

[ -f "$ENV_FILE" ] || { echo "Нет файла .env — сначала запусти bash install.sh"; exit 1; }

# Убираем прежнюю строку с этим ключом и дописываем новую.
grep -v "^${NAME}=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
printf '%s=%s\n' "$NAME" "$VALUE" >> "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "✓ $NAME записан в .env"

if systemctl is-enabled nutrition-bot >/dev/null 2>&1; then
    ${SUDO:-} systemctl restart nutrition-bot
    sleep 3
    if systemctl is-active --quiet nutrition-bot; then
        echo "✓ бот перезапущен и работает"
    else
        echo "✗ бот не поднялся, смотри: journalctl -u nutrition-bot -n 30"
        exit 1
    fi
fi
