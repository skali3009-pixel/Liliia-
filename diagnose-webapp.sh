#!/usr/bin/env bash
# Проверка, почему мини-приложение не отвечает по HTTPS.
#   bash diagnose-webapp.sh
# Секретов не печатает — вывод можно присылать целиком.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
PORT="${WEBAPP_PORT:-8080}"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

DOMAIN="$(sed -n 's|^WEBAPP_URL=https://||p' "$ENV_FILE" 2>/dev/null | tail -n1)"

hdr() { printf "\n\033[1;36m── %s\033[0m\n" "$*"; }
ok()  { printf "\033[1;32m  ✓ %s\033[0m\n" "$*"; }
bad() { printf "\033[1;31m  ✗ %s\033[0m\n" "$*"; }
inf() { printf "    %s\n" "$*"; }

echo "Адрес приложения: ${DOMAIN:-не задан}"

# 1. Бот и его веб-сервер
hdr "1. Бот"
if systemctl is-active --quiet nutrition-bot; then
    ok "служба работает"
else
    bad "служба не работает — веб-серверу неоткуда взяться"
    $SUDO journalctl -u nutrition-bot -n 15 --no-pager | sed 's/^/    /'
fi

hdr "2. Веб-сервер приложения (внутри сервера)"
if curl -sf --max-time 5 "http://127.0.0.1:$PORT/health" >/dev/null; then
    ok "отвечает на 127.0.0.1:$PORT"
else
    bad "не отвечает на 127.0.0.1:$PORT"
    inf "последние строки лога бота:"
    $SUDO journalctl -u nutrition-bot -n 20 --no-pager | grep -iE "error|traceback|exception|модул|import" | tail -8 | sed 's/^/    /'
fi

# 3. Caddy
hdr "3. Caddy (выдаёт HTTPS)"
if systemctl is-active --quiet caddy; then
    ok "служба работает"
else
    bad "служба не работает"
fi
$SUDO journalctl -u caddy -n 25 --no-pager 2>/dev/null \
    | grep -iE "error|obtain|certificate|challenge|timeout|refused" | tail -6 | sed 's/^/    /'

# 4. Порты
hdr "4. Открытые порты"
for p in 80 443 "$PORT"; do
    if ss -tln 2>/dev/null | grep -q ":$p "; then ok "порт $p слушается"; else bad "порт $p никто не слушает"; fi
done

# 5. Файрвол — самая частая причина
hdr "5. Файрвол"
if command -v ufw >/dev/null && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
    inf "ufw включён:"
    $SUDO ufw status | sed 's/^/    /'
    if ! $SUDO ufw status | grep -qE "^80[/ ]|^443[/ ]|Nginx|Caddy"; then
        bad "порты 80 и 443 закрыты — Let's Encrypt не сможет выдать сертификат"
        inf "открываю их…"
        $SUDO ufw allow 80/tcp >/dev/null 2>&1
        $SUDO ufw allow 443/tcp >/dev/null 2>&1
        ok "порты 80 и 443 открыты"
    else
        ok "80 и 443 разрешены"
    fi
else
    ok "ufw выключен или не установлен (значит, он не мешает)"
fi

if $SUDO iptables -L INPUT -n 2>/dev/null | grep -qE "DROP|REJECT"; then
    inf "внимание: в iptables есть запрещающие правила — возможен внешний файрвол провайдера"
fi

# 6. Достучаться снаружи
hdr "6. Проверка доступа снаружи"
if [ -n "$DOMAIN" ]; then
    RESOLVED="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1)"
    inf "$DOMAIN → ${RESOLVED:-не резолвится}"

    CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$DOMAIN/health" 2>/dev/null)"
    [ "$CODE" = "200" ] && ok "HTTP отвечает ($CODE)" || bad "HTTP не отвечает (код: ${CODE:-нет ответа})"

    CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/health" 2>/dev/null)"
    [ "$CODE" = "200" ] && ok "HTTPS отвечает ($CODE) — всё в порядке!" || bad "HTTPS не отвечает (код: ${CODE:-нет ответа})"
fi

hdr "Готово"
echo "  Пришли этот вывод целиком — в нём нет ни токенов, ни ключей."
