#!/usr/bin/env bash
# Добавить или заменить ключ в .env и перезапустить бота.
#
#   bash set-key.sh ANTHROPIC_API_KEY
#   bash set-key.sh VOICE_API_KEY

set -euo pipefail
umask 077

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

# Читаем вставку до пустой строки: мессенджер может добавить переносы в ключ.
# Один read принимал только первую строку, а хвост попадал в терминал при
# восстановлении echo. Весь блок ввода скрыт, включая все строки вставки.
read_secret() {
    local part=""
    while IFS= read -r -s part || [ -n "$part" ]; do
        [ -n "$part" ] || break
        VALUE+="$part"
        part=""
    done
}

if [ -z "$VALUE" ]; then
    if (: </dev/tty) 2>/dev/null; then TTY_IN=/dev/tty; else TTY_IN=/dev/stdin; fi
    if [ "$TTY_IN" = /dev/tty ]; then
        TTY_MODE="$(stty -g </dev/tty)"
        trap 'stty "$TTY_MODE" </dev/tty 2>/dev/null || true' EXIT
        stty -echo </dev/tty
    fi
    echo "Вставь значение для $NAME целиком. Нажми Enter, затем ещё раз Enter (пустая строка):"
    if [ "$TTY_IN" = /dev/tty ]; then
        read_secret </dev/tty
        stty "$TTY_MODE" </dev/tty
        trap - EXIT
    else
        read_secret
    fi
    echo
fi

# Пробелы и переносы по краям при вставке — обычное дело.
VALUE="$(printf '%s' "$VALUE" | tr -d '[:space:]')"

[ -n "$VALUE" ] || { echo "✗ Пустое значение, ничего не изменил."; exit 1; }

[ -f "$ENV_FILE" ] || { echo "Нет файла .env — сначала запусти bash install.sh"; exit 1; }

# Защита от самой частой ошибки: вставили текст-заглушку из инструкции
# вместо настоящего ключа.
reject() { echo "✗ Это не похоже на настоящий ключ: $1"; echo "  Скопируй ключ целиком из личного кабинета и вставь его в отдельный запрос скрипта."; exit 1; }

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
        # Длина секрета не является контрактом API. Проверяем у провайдера,
        # а не отбрасываем новые форматы по догадке о числе символов.
        ;;
    VOICE_API_KEY)
        case "$VALUE" in gsk_*|sk-*) ;; *) reject "ключ Groq начинается с gsk_, ключ OpenAI — с sk-";; esac ;;
    BOT_TOKEN)
        case "$VALUE" in *:*) ;; *) reject "токен бота выглядит как 8123456789:AAF...";; esac ;;
esac

# Спрашиваем сам сервис, рабочий ли ключ: лучше узнать это здесь, чем потом
# гадать над ошибкой в Telegram.
verify_key() {
    if [ "$NAME" = ANTHROPIC_API_KEY ]; then
        command -v curl >/dev/null 2>&1 || {
            echo "✗ Не могу проверить ключ: curl не установлен. В файл ничего не записал."
            exit 1
        }
        local code=""
        echo "  Проверяю ключ у Anthropic…"
        code="$(curl -s --max-time 20 --output /dev/null --write-out '%{http_code}' \
            https://api.anthropic.com/v1/models \
            -H "x-api-key: $VALUE" -H "anthropic-version: 2023-06-01" || true)"
        case "$code" in
            200) echo "  ✓ сервис принял ключ"; return 0 ;;
            401) echo "  ✗ Anthropic не принял ключ (HTTP 401): проверь полноту, срок действия и тип ключа." ;;
            400) echo "  ✗ Anthropic отклонил запрос (HTTP 400). Проверь, привязан ли ключ к рабочему пространству; для общего ключа может требоваться его ID." ;;
            402) echo "  ✗ Anthropic сообщил о проблеме оплаты (HTTP 402). Проверь Billing этого аккаунта." ;;
            403) echo "  ✗ Anthropic запретил доступ (HTTP 403). Проверь права ключа и аккаунта." ;;
            429) echo "  ✗ Anthropic ограничил запросы (HTTP 429). Повтори проверку позже." ;;
            *) echo "  ✗ Не удалось подтвердить ключ у Anthropic. Повтори проверку позже." ;;
        esac
        echo "    В файл ничего не записал; установленный ключ сохранён."
        exit 1
    fi
    command -v curl >/dev/null 2>&1 || return 0

    local answer=""
    case "$NAME" in
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
