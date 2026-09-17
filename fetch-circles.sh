#!/usr/bin/env bash
# Скачать кружки Аи по ссылкам от HeyGen и положить туда, где их ждёт бот.
#
# Ссылки подписанные и живут около недели — поэтому передаются аргументами, а
# не лежат в репозитории.
#
#   bash fetch-circles.sh 'hello=<ссылка>' 'ready=<ссылка>'
#
# Кавычки обязательны: в ссылках есть знаки, которые консоль иначе съест.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

cd "$DIR"
"$PYTHON" -m services.fetch_circles "$@"
