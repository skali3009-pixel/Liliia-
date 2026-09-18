#!/usr/bin/env bash
# Дневной потолок расходов на модель, доллары.
#
#   bash set-limit.sh        — показать текущий
#   bash set-limit.sh 30     — поднять до 30 $ в сутки
#
# Когда потолок исчерпан, отключается только распознавание фото и голоса.
# Дневник, тренировки и всё остальное продолжают работать: люди не должны
# терять свои записи из-за того, что кончились деньги на распознавание.
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
SERVICE="nutrition-bot"
NEW="${1:-}"

[ -f "$ENV_FILE" ] || { echo "Не нашёл $ENV_FILE — бот точно установлен?"; exit 1; }

current="$(grep -E '^DAILY_COST_LIMIT_USD=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"

if [ -z "$NEW" ]; then
  echo "Дневной потолок сейчас: ${current:-20} \$"
  echo "Изменить: bash set-limit.sh <сумма>"
  exit 0
fi

# Только число: мусор в этой строке роняет запуск бота.
if ! printf '%s' "$NEW" | grep -qE '^[0-9]+([.][0-9]+)?$'; then
  echo "Сумма — это число долларов, например 30. Получено: $NEW"
  exit 1
fi

if grep -qE '^DAILY_COST_LIMIT_USD=' "$ENV_FILE"; then
  sed -i "s|^DAILY_COST_LIMIT_USD=.*|DAILY_COST_LIMIT_USD=$NEW|" "$ENV_FILE"
else
  printf 'DAILY_COST_LIMIT_USD=%s\n' "$NEW" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

echo "Потолок: было ${current:-20} \$, стало $NEW \$ в сутки."
echo "Помни, что в кабинете Anthropic стоит ещё и месячный лимит — он главнее."

systemctl restart "$SERVICE" 2>/dev/null || true
sleep 5
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  echo "Бот перезапущен."
else
  echo "Бот не поднялся — посмотри: journalctl -u $SERVICE -n 50"
fi
