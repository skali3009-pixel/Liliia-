#!/usr/bin/env bash
# Включить ежедневные резервные копии.
#
#   bash setup-backup.sh          — включить
#   bash setup-backup.sh --off    — выключить
#
# После включения сервер каждую ночь делает копию базы и фотографий,
# отправляет её владельцу в Телеграм и убирает старые копии с диска.
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="nutrition-bot-backup"
AT="04:30"

if [ "${1:-}" = "--off" ]; then
  systemctl disable --now "$UNIT.timer" 2>/dev/null || true
  rm -f "/etc/systemd/system/$UNIT.service" "/etc/systemd/system/$UNIT.timer"
  systemctl daemon-reload
  echo "Резервное копирование выключено."
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "Запусти от root: sudo bash setup-backup.sh"
  exit 1
fi

cat > "/etc/systemd/system/$UNIT.service" <<UNIT_EOF
[Unit]
Description=Резервная копия бота питания
After=network-online.target postgresql.service

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash $APP_DIR/backup.sh
UNIT_EOF

cat > "/etc/systemd/system/$UNIT.timer" <<TIMER_EOF
[Unit]
Description=Ежедневная резервная копия бота питания

[Timer]
OnCalendar=*-*-* $AT
# Если сервер в это время был выключен — копия сделается при следующем старте.
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
TIMER_EOF

systemctl daemon-reload
systemctl enable --now "$UNIT.timer"

echo "Готово. Копия будет делаться каждую ночь в $AT."
echo "Проверить: systemctl list-timers $UNIT.timer"
echo "Сделать копию прямо сейчас: bash backup.sh"
