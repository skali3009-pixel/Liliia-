#!/usr/bin/env bash
#
# Установка бота питания на сервер (Ubuntu/Debian).
#
# Запуск из папки с проектом:
#   bash install.sh
#
# Скрипт делает всё сам: ставит зависимости и PostgreSQL, создаёт базу,
# спрашивает токены, настраивает автозапуск и включает бота.
# Повторный запуск безопасен — можно использовать для переустановки.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="nutrition-bot"
DB_NAME="nutrition_bot"
DB_USER="nutrition_bot"
ENV_FILE="$APP_DIR/.env"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
APP_USER="$(id -un)"

say()  { printf "\n\033[1;36m%s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m  ✓ %s\033[0m\n" "$*"; }
fail() { printf "\n\033[1;31m  ✗ %s\033[0m\n" "$*" >&2; exit 1; }

[ -f "$APP_DIR/requirements.txt" ] || fail "Запускай скрипт из папки проекта: cd ~/nutrition-bot && bash install.sh"

# --- 1. Системные пакеты -----------------------------------------------------
say "Шаг 1/6. Ставлю системные пакеты (python, postgresql)…"
$SUDO apt-get update -qq
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip postgresql >/dev/null
$SUDO systemctl enable --now postgresql >/dev/null 2>&1 || true
ok "пакеты установлены"

# --- 2. Виртуальное окружение и зависимости ----------------------------------
say "Шаг 2/6. Ставлю библиотеки Python (это самый долгий шаг, 1-3 минуты)…"
[ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "библиотеки установлены"

# --- 3. База данных ----------------------------------------------------------
say "Шаг 3/6. Создаю базу данных…"
DB_PASSWORD="$(openssl rand -hex 16)"

# Обращение к базе от имени системного пользователя postgres — и из-под root,
# и из-под обычного пользователя с sudo.
run_as_postgres() {
    if [ "$(id -u)" -eq 0 ]; then
        if command -v runuser >/dev/null 2>&1; then
            runuser -u postgres -- "$@"
        else
            su postgres -s /bin/sh -c "$(printf '%q ' "$@")"
        fi
    else
        sudo -u postgres "$@"
    fi
}
psql_su() { run_as_postgres psql -qtAc "$1"; }

run_as_postgres psql -qtAc "SELECT 1" >/dev/null 2>&1 \
    || fail "PostgreSQL не отвечает. Проверь: sudo systemctl status postgresql"

if [ "$(psql_su "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")" = "1" ]; then
    psql_su "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" >/dev/null
else
    psql_su "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" >/dev/null
fi

if [ "$(psql_su "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" != "1" ]; then
    psql_su "CREATE DATABASE $DB_NAME OWNER $DB_USER;" >/dev/null
fi
ok "база $DB_NAME готова (пароль сгенерирован автоматически)"

# --- 4. Токены ---------------------------------------------------------------
say "Шаг 4/6. Токены."

# Если .env уже есть — переиспользуем то, что там лежит, и не спрашиваем заново.
read_env_value() {
    [ -f "$ENV_FILE" ] || return 0
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1
}

BOT_TOKEN="$(read_env_value BOT_TOKEN)"
ANTHROPIC_API_KEY="$(read_env_value ANTHROPIC_API_KEY)"

case "$BOT_TOKEN" in ""|*ExampleToken*) BOT_TOKEN="";; esac
case "$ANTHROPIC_API_KEY" in ""|*your-key-here*) ANTHROPIC_API_KEY="";; esac

while ! printf '%s' "$BOT_TOKEN" | grep -qE '^[0-9]{6,}:[A-Za-z0-9_-]{30,}$'; do
    echo "  Вставь токен бота от @BotFather (вид: 8123456789:AAF...) и нажми Enter:"
    read -r BOT_TOKEN
    printf '%s' "$BOT_TOKEN" | grep -qE '^[0-9]{6,}:[A-Za-z0-9_-]{30,}$' \
        || echo "  Не похоже на токен — там цифры, двоеточие и длинный код. Попробуй ещё раз."
done
ok "токен бота принят"

while ! printf '%s' "$ANTHROPIC_API_KEY" | grep -qE '^sk-ant-'; do
    echo "  Вставь ключ Anthropic (вид: sk-ant-api03-...) и нажми Enter:"
    read -r ANTHROPIC_API_KEY
    printf '%s' "$ANTHROPIC_API_KEY" | grep -qE '^sk-ant-' \
        || echo "  Ключ должен начинаться с sk-ant- . Попробуй ещё раз."
done
ok "ключ Anthropic принят"

umask 077
cat > "$ENV_FILE" <<ENV
BOT_TOKEN=$BOT_TOKEN
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
DATABASE_URL=postgresql+asyncpg://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
ENV
chmod 600 "$ENV_FILE"
ok "настройки сохранены в .env (файл закрыт от посторонних)"

# --- 5. Автозапуск -----------------------------------------------------------
say "Шаг 5/6. Настраиваю автозапуск (systemd)…"
$SUDO tee "/etc/systemd/system/$SERVICE_NAME.service" >/dev/null <<UNIT
[Unit]
Description=Nutrition & fitness Telegram bot
After=network.target postgresql.service

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5
EnvironmentFile=$ENV_FILE

[Install]
WantedBy=multi-user.target
UNIT

$SUDO systemctl daemon-reload
$SUDO systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
$SUDO systemctl restart "$SERVICE_NAME"
ok "автозапуск настроен — бот будет подниматься сам после перезагрузки"

# --- 6. Проверка -------------------------------------------------------------
say "Шаг 6/6. Проверяю, что бот запустился…"
sleep 5

if ! $SUDO systemctl is-active --quiet "$SERVICE_NAME"; then
    printf "\n\033[1;31m  ✗ Бот не запустился. Последние строки лога:\033[0m\n\n"
    $SUDO journalctl -u "$SERVICE_NAME" -n 30 --no-pager
    printf "\n  Скопируй текст выше и пришли его — разберём.\n"
    exit 1
fi

BOT_USERNAME="$(curl -s --max-time 10 "https://api.telegram.org/bot$BOT_TOKEN/getMe" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('result',{}).get('username',''))" 2>/dev/null || true)"

printf "\n\033[1;32m═══════════════════════════════════════════\033[0m\n"
printf "\033[1;32m  ГОТОВО! Бот работает.\033[0m\n"
printf "\033[1;32m═══════════════════════════════════════════\033[0m\n\n"
if [ -n "$BOT_USERNAME" ]; then
    echo "  Открой в Telegram:  https://t.me/$BOT_USERNAME"
    echo "  и напиши ему:       /start"
else
    echo "  Открой своего бота в Telegram и напиши: /start"
fi
cat <<INFO

  Полезные команды на будущее:
    sudo systemctl status $SERVICE_NAME     — работает ли бот
    sudo journalctl -u $SERVICE_NAME -f     — смотреть логи вживую (выход: Ctrl+C)
    sudo systemctl restart $SERVICE_NAME    — перезапустить

  Обновить бота после моих правок:
    cd $APP_DIR && git pull && sudo systemctl restart $SERVICE_NAME

INFO
