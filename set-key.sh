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

if [ -z "$NAME" ]; then
    echo "Как пользоваться:"
    echo "  bash set-key.sh ANTHROPIC_API_KEY   — распознавание еды по фото"
    echo "  bash set-key.sh VOICE_API_KEY       — голосовые сообщения"
    echo
    echo "Ключ вводить в команду не нужно — скрипт спросит его отдельно."
    exit 1
fi

# Ключ длинный, и вставлять его в одну строку с командой — верный способ
# что-нибудь потерять. Поэтому спрашиваем отдельным вопросом, на чистой строке.
if [ -z "$VALUE" ]; then
    if (: </dev/tty) 2>/dev/null; then TTY_IN=/dev/tty; else TTY_IN=/dev/stdin; fi
    # Выбрасываем всё, что уже лежит в буфере ввода от прежних вставок.
    if [ "$TTY_IN" = /dev/tty ]; then
        while read -r -t 0.3 _ </dev/tty 2>/dev/null; do :; done
    fi
    echo "Вставь значение для $NAME и нажми Enter:"
    read -r VALUE <"$TTY_IN"
fi

# Пробелы и переносы по краям при вставке — обычное дело.
VALUE="$(printf '%s' "$VALUE" | tr -d '[:space:]')"

[ -n "$VALUE" ] || { echo "✗ Пустое значение, ничего не изменил."; exit 1; }

[ -f "$ENV_FILE" ] || { echo "Нет файла .env — сначала запусти bash install.sh"; exit 1; }

# Защита от самой частой ошибки: вставили текст-заглушку из инструкции
# вместо настоящего ключа.
reject() { echo "✗ Это не похоже на настоящий ключ: $1"; echo "  Скопируй ключ целиком из личного кабинета и вставь его в команду."; exit 1; }

# Настоящий ключ — только латиница, цифры и знаки, так что кириллица в нём
# означает, что скопировали текст из инструкции.
case "$VALUE" in
    *[!\ -~]*) reject "в нём русские буквы (это текст из инструкции)";;
esac

# Слова-заглушки ищем только в коротких значениях: в длинном случайном ключе
# такое сочетание символов может встретиться и само по себе.
if [ "${#VALUE}" -lt 60 ]; then
    case "$VALUE" in
        *твой*|*ваш*|*your*|*_ключ*|*xxx*|*XXX*) reject "в нём слово-заглушка";;
    esac
fi

case "$NAME" in
    ANTHROPIC_API_KEY)
        case "$VALUE" in sk-ant-*) ;; *) reject "ключ Anthropic начинается с sk-ant-";; esac
        [ "${#VALUE}" -ge 80 ] || reject "он слишком короткий (${#VALUE} символов вместо ~108) — вставился не целиком" ;;
    VOICE_API_KEY)
        case "$VALUE" in gsk_*|sk-*) ;; *) reject "ключ Groq начинается с gsk_, ключ OpenAI — с sk-";; esac ;;
    BOT_TOKEN)
        case "$VALUE" in *:*) ;; *) reject "токен бота выглядит как 8123456789:AAF...";; esac ;;
esac

# Спрашиваем сам сервис, рабочий ли ключ: лучше узнать это здесь, чем потом
# гадать над ошибкой в Telegram.
verify_key() {
    command -v curl >/dev/null 2>&1 || return 0

    local answer=""
    case "$NAME" in
        ANTHROPIC_API_KEY)
            echo "  Проверяю ключ у Anthropic…"
            answer="$(curl -s --max-time 20 https://api.anthropic.com/v1/models \
                -H "x-api-key: $VALUE" -H "anthropic-version: 2023-06-01" || true)" ;;
        VOICE_API_KEY)
            echo "  Проверяю ключ у сервиса распознавания речи…"
            answer="$(curl -s --max-time 20 "${VOICE_BASE_URL:-https://api.groq.com/openai/v1}/models" \
                -H "Authorization: Bearer $VALUE" || true)" ;;
        *) return 0 ;;
    esac

    case "$answer" in
        *'"data"'*)
            echo "  ✓ сервис принял ключ" ;;
        *authentication_error*|*invalid_api_key*|*"Invalid API Key"*|*"invalid x-api-key"*)
            echo "  ✗ Сервис не принял этот ключ: он неверный, отозван или скопирован не целиком."
            echo "    Создай новый ключ в личном кабинете и запусти команду ещё раз."
            echo "    В файл ничего не записал."
            exit 1 ;;
        *credit*|*billing*)
            echo "  ⚠ Ключ верный, но на счёте нет денег — пополни баланс в кабинете." ;;
        "")
            echo "  ⚠ Сервис не ответил (нет сети?) — записываю ключ как есть." ;;
        *)
            echo "  ⚠ Непонятный ответ сервиса — записываю ключ как есть." ;;
    esac
}

verify_key

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
