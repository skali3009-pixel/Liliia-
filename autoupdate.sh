#!/usr/bin/env bash
# Включить автообновление бота: сервер сам подтягивает новые версии.
#
# Запускается один раз. После этого каждые 10 минут сервер проверяет git,
# и если появилась новая версия — обновляется и перезапускает бота. Если
# новая версия не поднялась, откатывается на прежнюю.
#
#   bash autoupdate.sh          — включить
#   bash autoupdate.sh --off    — выключить
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="nutrition-bot-update"
EVERY="10min"

if [ "${1:-}" = "--off" ]; then
  systemctl disable --now "$UNIT.timer" 2>/dev/null || true
  rm -f "/etc/systemd/system/$UNIT.service" "/etc/systemd/system/$UNIT.timer"
  systemctl daemon-reload
  echo "Автообновление выключено."
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "Запусти от root: sudo bash autoupdate.sh"
  exit 1
fi

cat > "/etc/systemd/system/$UNIT.service" <<UNIT_EOF
[Unit]
Description=Обновление бота питания из git
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash $APP_DIR/update.sh
UNIT_EOF

cat > "/etc/systemd/system/$UNIT.timer" <<UNIT_EOF
[Unit]
Description=Проверять обновления бота каждые $EVERY

[Timer]
OnBootSec=3min
OnUnitActiveSec=$EVERY
# Разброс, чтобы проверки не приходились на одну и ту же секунду.
RandomizedDelaySec=60
Persistent=true

[Install]
WantedBy=timers.target
UNIT_EOF

chmod +x "$APP_DIR/update.sh"
systemctl daemon-reload
systemctl enable --now "$UNIT.timer"

echo "Автообновление включено: проверка каждые $EVERY."
echo
echo "Обновляюсь прямо сейчас…"
bash "$APP_DIR/update.sh" || true
echo
echo "Что дальше:"
echo "  Ничего. Новые версии приедут сами."
echo "  Проверить:  systemctl list-timers $UNIT.timer"
echo "  Логи:       journalctl -u $UNIT -n 30 --no-pager"
echo "  Выключить:  bash autoupdate.sh --off"
