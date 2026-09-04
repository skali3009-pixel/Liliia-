#!/usr/bin/env bash
# Заполнить реквизиты в оферте, политике данных и согласиях.
#
#   bash set-legal.sh
#
# Скрипт задаёт четыре вопроса по-русски, сам подставляет имя бота и
# перезаписывает .env. Руками файл править не нужно.

set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"

[ -f "$ENV_FILE" ] || { echo "Нет файла .env — сначала запусти bash install.sh"; exit 1; }

# Читаем текущие значения, чтобы показать их как подсказку и не потерять.
current() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | sed 's/^"//; s/"$//'; }

BOT_TOKEN_VALUE="$(current BOT_TOKEN)"
OLD_OWNER="$(current LEGAL_OWNER)"
OLD_REQ="$(current LEGAL_REQUISITES)"
OLD_EMAIL="$(current LEGAL_EMAIL)"
OLD_BOT="$(current BOT_USERNAME)"

if (: </dev/tty) 2>/dev/null; then TTY_IN=/dev/tty; else TTY_IN=/dev/stdin; fi

# Вопрос с подсказкой: пустой ответ оставляет прежнее значение.
ask() {
    local prompt="$1" old="$2" answer=""
    # Вопрос печатаем в stderr: stdout уходит в переменную вызывающему.
    echo >&2
    echo "$prompt" >&2
    [ -n "$old" ] && echo "   Сейчас: $old  (Enter — оставить как есть)" >&2
    printf '   > ' >&2
    read -r answer <"$TTY_IN"
    # Пробелы по краям при вставке с телефона — обычное дело.
    answer="$(printf '%s' "$answer" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    printf '%s' "${answer:-$old}"
}

echo "Заполняем реквизиты для оферты и политики данных."
echo "Это то, что увидит человек внизу каждого документа."

OWNER="$(ask 'Как тебя называть в документах?
   Если статуса пока нет  — «Скалий Лилия Владимировна»
   Если самозанятая        — «Самозанятая Скалий Л. В.»
   Если через ИП           — «ИП Скалий Л. В.»' "$OLD_OWNER")"

REQUISITES="$(ask 'Реквизиты одной строкой (можно оставить пустым, пока нет статуса).
   Пример: «ИНН 770000000000, ОГРНИП 300000000000000, г. Москва»' "$OLD_REQ")"

EMAIL="$(ask 'Почта для писем от пользователей — про данные, возвраты, вопросы.
   Обязательна по закону о персональных данных. Пример: liliia@example.com' "$OLD_EMAIL")"

# Имя бота знает сам Telegram — незачем спрашивать и рисковать опечаткой.
BOT_NAME="$OLD_BOT"
if [ -z "$BOT_NAME" ] && [ -n "$BOT_TOKEN_VALUE" ] && command -v curl >/dev/null 2>&1; then
    echo
    echo "Спрашиваю имя бота у Telegram…"
    DETECTED="$(curl -s --max-time 15 "https://api.telegram.org/bot$BOT_TOKEN_VALUE/getMe" \
        | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
    if [ -n "$DETECTED" ]; then
        BOT_NAME="$DETECTED"
        echo "   ✓ это @$BOT_NAME"
    fi
fi
[ -n "$BOT_NAME" ] || BOT_NAME="$(ask 'Имя бота без @ (например Fit_Scalia_bot)' "$OLD_BOT")"
BOT_NAME="${BOT_NAME#@}"

# Две ошибки, из-за которых документ становится бесполезным: нет владельца
# и нет обратной связи. Остальное можно дописать позже.
[ -n "$OWNER" ] || { echo; echo "✗ Без имени владельца документы подписывать нечем. Ничего не изменил."; exit 1; }
case "$EMAIL" in
    *@*.*) ;;
    *) echo; echo "✗ «$EMAIL» не похоже на почту. Ничего не изменил."; exit 1;;
esac

echo
echo "Проверь, как это будет выглядеть в документах:"
echo "  Владелец:  $OWNER"
echo "  Реквизиты: ${REQUISITES:-— (не указаны)}"
echo "  Почта:     $EMAIL"
echo "  Бот:       @$BOT_NAME"
echo
printf 'Всё верно? (да / нет): '
read -r CONFIRM <"$TTY_IN"
case "$CONFIRM" in
    д*|Д*|y*|Y*) ;;
    *) echo "Ничего не изменил. Запусти команду заново, когда будешь готова."; exit 0;;
esac

# В .env значения с пробелами и кириллицей обязаны быть в кавычках: файл
# читают и Python, и systemd, и оба ждут кавычки вокруг таких строк.
quote() { printf '"%s"' "$(printf '%s' "$1" | sed 's/[\\"$`]/\\&/g')"; }

set_var() {
    grep -v "^$1=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
    printf '%s=%s\n' "$1" "$(quote "$2")" >> "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
}

set_var LEGAL_OWNER "$OWNER"
set_var LEGAL_REQUISITES "$REQUISITES"
set_var LEGAL_EMAIL "$EMAIL"
set_var BOT_USERNAME "$BOT_NAME"
chmod 600 "$ENV_FILE"

echo "✓ реквизиты записаны"

if systemctl is-enabled nutrition-bot >/dev/null 2>&1; then
    ${SUDO:-} systemctl restart nutrition-bot
    sleep 3
    if systemctl is-active --quiet nutrition-bot; then
        echo "✓ бот перезапущен"
    else
        echo "✗ бот не поднялся, смотри: journalctl -u nutrition-bot -n 30"
        exit 1
    fi
fi

WEBAPP="$(current WEBAPP_URL)"
if [ -n "$WEBAPP" ]; then
    echo
    echo "Открой и посмотри, всё ли на месте:"
    for slug in offer privacy consent marketing; do
        echo "  ${WEBAPP%/}/legal/$slug"
    done
fi
echo
echo "Готово. В боте документы всегда под рукой по команде /legal."
