#!/usr/bin/env bash
#
# Подключение мини-приложения: HTTPS-адрес + кнопка в боте.
#
#   bash setup-webapp.sh                 — бесплатный адрес из IP сервера
#   bash setup-webapp.sh myfood.ru       — свой домен (должен указывать на этот сервер)
#
# Что делает: ставит Caddy (он сам получает бесплатный сертификат
# Let's Encrypt и продлевает его), направляет его на локальный порт бота,
# прописывает адрес в .env и перезапускает бота.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
SERVICE_NAME="nutrition-bot"
WEBAPP_PORT="${WEBAPP_PORT:-8080}"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

say()  { printf "\n\033[1;36m%s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m  ✓ %s\033[0m\n" "$*"; }
fail() { printf "\n\033[1;31m  ✗ %s\033[0m\n" "$*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || fail "Нет файла .env — сначала запусти bash install.sh"

# --- 1. Адрес ----------------------------------------------------------------
say "Шаг 1/5. Определяю адрес приложения…"

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
    SERVER_IP="$(curl -s --max-time 10 https://api.ipify.org || true)"
    [ -n "$SERVER_IP" ] || fail "Не удалось определить IP сервера. Передай домен: bash setup-webapp.sh мойдомен.ру"
    # nip.io превращает IP в имя: 1.2.3.4 → 1-2-3-4.nip.io, и на него
    # выдаётся настоящий сертификат.
    DOMAIN="${SERVER_IP//./-}.nip.io"
    ok "бесплатный адрес: $DOMAIN (из IP $SERVER_IP)"
else
    ok "твой домен: $DOMAIN"
    echo "    Убедись, что A-запись домена указывает на этот сервер,"
    echo "    иначе сертификат не выпустится."
fi

# --- 2. Caddy ----------------------------------------------------------------
say "Шаг 2/5. Ставлю Caddy (веб-сервер с автоматическим HTTPS)…"
if ! command -v caddy >/dev/null 2>&1; then
    $SUDO apt-get update -qq
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        debian-keyring debian-archive-keyring apt-transport-https curl gnupg >/dev/null
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | $SUDO gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        | $SUDO tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    $SUDO apt-get update -qq
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy >/dev/null
fi
ok "Caddy установлен"

# --- 3. Настройка ------------------------------------------------------------
say "Шаг 3/5. Настраиваю HTTPS для $DOMAIN…"
$SUDO tee /etc/caddy/Caddyfile >/dev/null <<CADDY
$DOMAIN {
    reverse_proxy 127.0.0.1:$WEBAPP_PORT
}
CADDY

$SUDO systemctl reload caddy 2>/dev/null || $SUDO systemctl restart caddy
ok "Caddy настроен (сертификат он получит сам за несколько секунд)"

# --- 4. Адрес в настройках бота ----------------------------------------------
say "Шаг 4/5. Прописываю адрес в настройки бота…"
WEBAPP_URL="https://$DOMAIN"
grep -v "^WEBAPP_URL=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
printf 'WEBAPP_URL=%s\n' "$WEBAPP_URL" >> "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"
$SUDO systemctl restart "$SERVICE_NAME"
ok "адрес сохранён: $WEBAPP_URL"

# --- 5. Проверка -------------------------------------------------------------
say "Шаг 5/5. Проверяю, что всё поднялось…"
sleep 8

for attempt in 1 2 3 4 5; do
    if curl -sf --max-time 15 "$WEBAPP_URL/health" >/dev/null 2>&1; then
        printf "\n\033[1;32m═══════════════════════════════════════════\033[0m\n"
        printf "\033[1;32m  ГОТОВО! Приложение работает.\033[0m\n"
        printf "\033[1;32m═══════════════════════════════════════════\033[0m\n\n"
        echo "  Адрес: $WEBAPP_URL"
        echo
        echo "  Открой бота в Telegram — рядом с полем ввода появилась"
        echo "  кнопка «Дневник». Нажми её."
        echo
        echo "  Если кнопки нет — закрой и открой чат заново."
        exit 0
    fi
    echo "  жду сертификат… ($attempt/5)"
    sleep 10
done

printf "\n\033[1;31m  ✗ Приложение пока не отвечает по HTTPS.\033[0m\n"
echo "  Проверь: sudo journalctl -u caddy -n 30 --no-pager"
echo "  и пришли вывод — разберём."
exit 1
