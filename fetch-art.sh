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
# hero   — портрет анфас, шапка «Сегодня»
# world  — гепард у арки, экран «Мой мир»
# moment — профиль, фон окна «Что происходит»
# sky    — гепард под звёздами, шапка «Прогресса»
# gym    — гепард в движении, шапка «Спорта»
download hero.png   "$CDN/hf_20260904_122511_42ef8f97-a0a3-4309-b45d-68ecbc1edf46.png"
download world.png  "$CDN/hf_20260904_122511_c6d26286-18ec-40f9-89a9-1d7d3d86292f.png"
download moment.png "$CDN/hf_20260904_122511_fddc3628-f8d7-420e-9dc3-9aff5f21f02e.png"
download sky.png    "$CDN/hf_20260904_122511_d57ed7c2-8d43-4d59-932f-3455abf64a21.png"
download gym.png    "$CDN/hf_20260904_171317_baaa67ef-3e6a-4903-9b29-a8853b81c7a7.png"
echo
echo "Готово. Перезапускать бота не нужно — обнови приложение в Telegram."
