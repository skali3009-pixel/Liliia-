#!/usr/bin/env bash
# Скачать фоновые арты приложения на сервер.
#
# Картинки лежат не в git (они большие и меняются отдельно от кода), а на
# CDN. Скрипт кладёт их в webapp/static/img/ — приложение подхватит их само.
# Без картинок приложение тоже работает: вместо арта будет градиент.
#
#   bash fetch-art.sh
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/webapp/static/img"
mkdir -p "$DIR"

CDN="https://d8j0ntlcm91z4.cloudfront.net/user_3G2THIaqFMEKEfdY5lQg4VK5iBT"

download() {
  local name="$1" url="$2"
  printf '  %-12s' "$name"
  if curl -fsS --max-time 120 -o "$DIR/$name.tmp" "$url"; then
    mv "$DIR/$name.tmp" "$DIR/$name"
    printf 'готово (%s)\n' "$(du -h "$DIR/$name" | cut -f1)"
  else
    rm -f "$DIR/$name.tmp"
    printf 'не скачалось — приложение покажет градиент\n'
  fi
}

echo "Качаю арты в $DIR"
download hero.png  "$CDN/hf_20260904_120533_c4cab18c-16a2-40bb-821d-1f41dcc20b4d.png"
download world.png "$CDN/hf_20260904_120233_fbec8d10-8c7c-4b30-840c-30e797c627e5.png"
echo
echo "Готово. Перезапускать бота не нужно — обнови приложение в Telegram."
