#!/usr/bin/env bash
# Включить сторожа: он замечает падение бота и пишет владельцу.
#
#   bash setup-watchdog.sh          — включить
#   bash setup-watchdog.sh --off    — выключить
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="nutrition-bot-watchdog"
EVERY="5min"

if [ "${1:-}" = "--off" ]; then
  systemctl disable --now "$UNIT.timer" 2>/dev/null || true
  rm -f "/etc/systemd/system/$UNIT.service" "/etc/systemd/system/$UNIT.timer"
  systemctl daemon-reload
  echo "Сторож выключен."
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "Запусти от root: sudo bash setup-watchdog.sh"
  exit 1
fi

cat > "/etc/systemd/system/$UNIT.service" <<UNIT_EOF
[Unit]
Description=Сторож бота питания
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash $APP_DIR/watchdog.sh
UNIT_EOF

cat > "/etc/systemd/system/$UNIT.timer" <<TIMER_EOF
[Unit]
Description=Проверка, что бот жив

[Timer]
OnBootSec=3min
OnUnitActiveSec=$EVERY

[Install]
WantedBy=timers.target
TIMER_EOF

systemctl daemon-reload
systemctl enable --now "$UNIT.timer"

echo "Сторож включён: проверка каждые $EVERY."
echo "Убедиться, что сообщение доходит: bash watchdog.sh --test"
