#!/usr/bin/env bash
# «Монтаж — FableCut»: запускает редактор на 127.0.0.1:7777 (только локально) и открывает браузер.
cd "$(dirname "$0")/FableCut" || exit 1
curl -s -o /dev/null http://127.0.0.1:7777/ || (node server.js > /tmp/fablecut.log 2>&1 &)
sleep 2
xdg-open http://localhost:7777 2>/dev/null || echo "Откройте http://localhost:7777"
