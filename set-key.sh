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

# Защита от самой частой ошибки: вставили текст-заглушку из инструкции
# вместо настоящего ключа.
reject() { echo "✗ Это не похоже на настоящий ключ: $1"; echo "  Скопируй ключ целиком из личного кабинета и вставь его в команду."; exit 1; }

case "$VALUE" in
    *[!\ -~]*)        reject "в нём русские буквы (это текст из инструкции)";;
    *твой*|*ваш*|*your*|*_ключ*|*xxx*) reject "в нём слово-заглушка";;
esac

case "$NAME" in
    ANTHROPIC_API_KEY)
        case "$VALUE" in sk-ant-*) ;; *) reject "ключ Anthropic начинается с sk-ant-";; esac ;;
    VOICE_API_KEY)
        case "$VALUE" in gsk_*|sk-*) ;; *) reject "ключ Groq начинается с gsk_, ключ OpenAI — с sk-";; esac ;;
    BOT_TOKEN)
        case "$VALUE" in *:*) ;; *) reject "токен бота выглядит как 8123456789:AAF...";; esac ;;
esac

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
