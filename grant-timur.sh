#!/usr/bin/env bash
# Технический доступ Тимура к серверу AURA — по его SSH-ключу.
#
#   bash grant-timur.sh            — завести или поправить доступ (повторять можно)
#   bash grant-timur.sh --check    — только показать, что есть, ничего не меняя
#   bash grant-timur.sh --remove   — убрать доступ целиком
#
# Секретов не печатает: ни ключей, ни .env, ни паролей. Вывод можно
# присылать целиком.
#
# Что получает Тимур — отдельный пользователь `timur`, вход только по ключу,
# и четыре команды через sudo, без пароля:
#
#   sudo aura-service status|restart|start|stop|timers  — служба бота
#   sudo aura-logs [-n 200] [-f] [--since …] [-u update] — журнал AURA
#   sudo aura-run <скрипт> [аргументы]                 — скрипты проекта
#   sudo aura-git [status|log|diff]                      — какая версия стоит
#
# Почему не права на папку. Проект лежит в /root, а чтобы дойти до него,
# пришлось бы открыть проход через /root. Через этот проход видно всё, что
# лежит рядом открытым: ночные копии базы (/root/nutrition-backups — там
# данные всех людей) и чужие боты. Поэтому файлов Тимур не читает вовсе, а
# код берёт с GitHub — на сервере стоит ровно то же, что в ветке.
#
# Оговорка, которую надо знать. Служба работает от root, а `aura-run`
# запускает скрипты проекта, которые Тимур может поменять через GitHub
# (автообновление привозит их само). Значит, по возможностям это близко к
# root — но это свойство «запись в GitHub + автообновление», а не этого
# скрипта: такую же власть ему уже даёт доступ к репозиторию.

set -uo pipefail

LOGIN="timur"
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHyuTu+vzFcoIAs8DWsg9bGN0eqd0Oqxj1+L658Voiw8 aura-timur-20261004'
EXPECTED_IP="72.56.90.120"
SERVICE="nutrition-bot"
SUDOERS="/etc/sudoers.d/aura-$LOGIN"
TOOLS_DIR="/usr/local/sbin"
TOOLS=(aura-service aura-logs aura-run aura-git)
# Скрипты проекта, которые можно запускать. Нет здесь намеренно:
# set-admin (кто владелец), set-legal (реквизиты), set-paywall (оплата),
# restore (подмена базы целиком) — это решения Лилии, а не обслуживание.
SCRIPTS="update status set-key fetch-art fetch-circles diagnose-webapp ensure-ops backup"

MODE="${1:-grant}"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
warn() { printf '  ⚠ %s\n' "$*"; }
fail() { printf '  ✗ %s\n' "$*"; exit 1; }

[ "$(id -u)" = 0 ] || fail "Запускать от root: в веб-консоли сервера так и есть."

# Где на самом деле живёт проект — спрашиваем у службы, а не верим записке.
APP_DIR="${AURA_APP_DIR:-$(systemctl show -p WorkingDirectory --value "$SERVICE" 2>/dev/null)}"
[ -n "$APP_DIR" ] || APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="$(systemctl show -p User --value "$SERVICE" 2>/dev/null)"

KEY_BODY="$(printf '%s' "$KEY" | awk '{print $2}')"

count_keys() {  # сколько ключей в файле, без содержимого
  [ -f "$1" ] || { echo 0; return; }
  grep -cE '^[^#]*(ssh-|ecdsa-|sk-)' "$1" 2>/dev/null || true
}

ROOT_KEYS_BEFORE="$(count_keys /root/.ssh/authorized_keys)"

# --- Что за сервер ----------------------------------------------------------
facts() {
  say "Сервер"
  say "  имя:        $(hostname)"
  say "  система:    $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-?}")"
  local ips public
  ips="$(hostname -I 2>/dev/null | xargs)"
  say "  адреса:     ${ips:-?}"
  public="$(curl -s -m 5 https://api.ipify.org 2>/dev/null || true)"
  [ -n "$public" ] && say "  внешний IP: $public"
  if printf ' %s %s ' "$ips" "$public" | grep -qF " $EXPECTED_IP "; then
    ok "IP $EXPECTED_IP из записей проекта совпадает"
  else
    warn "IP $EXPECTED_IP из записей проекта здесь не найден"
  fi

  say "Бот"
  if systemctl cat "$SERVICE" >/dev/null 2>&1; then
    say "  служба:     $SERVICE — $(systemctl is-active "$SERVICE" 2>/dev/null)"
    say "  папка:      $APP_DIR"
    say "  работает от: ${SERVICE_USER:-root}"
  else
    warn "службы $SERVICE на этом сервере нет — папку беру по месту скрипта: $APP_DIR"
  fi
  if [ -d "$APP_DIR/.git" ]; then
    say "  версия:     $(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null) на ветке $(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  fi
}

# --- SSH: только смотрим, ничего не меняем ----------------------------------
SSH_PORT=""
ssh_report() {
  say "SSH"
  local cfg
  cfg="$(sshd -T -C "user=$LOGIN,host=localhost,addr=127.0.0.1" 2>/dev/null || sshd -T 2>/dev/null || true)"
  if [ -z "$cfg" ]; then
    warn "не смог прочитать настройки sshd — порт считаю стандартным, 22"
    SSH_PORT=22
    return
  fi
  get() { printf '%s\n' "$cfg" | awk -v k="$1" '$1==k {$1=""; sub(/^ /,""); print}' | paste -sd' ' -; }
  SSH_PORT="$(printf '%s\n' "$cfg" | awk '$1=="port"{print $2; exit}')"
  say "  порт:                 ${SSH_PORT:-22}"
  say "  вход по ключу:        $(get pubkeyauthentication)"
  say "  вход по паролю:       $(get passwordauthentication)"
  say "  root по SSH:          $(get permitrootlogin)"
  local allow_users allow_groups deny_users
  allow_users="$(get allowusers)"; allow_groups="$(get allowgroups)"; deny_users="$(get denyusers)"
  [ "$(get pubkeyauthentication)" = "no" ] && warn "вход по ключу выключен — Тимур не войдёт; настройку не трогаю"
  if [ -n "$allow_users" ] && ! printf ' %s ' "$allow_users" | grep -qE " ($LOGIN|$LOGIN@[^ ]*) "; then
    warn "в sshd стоит AllowUsers ($allow_users) без $LOGIN — Тимур не войдёт; настройку не трогаю"
  fi
  [ -n "$allow_groups" ] && warn "в sshd стоит AllowGroups ($allow_groups) — проверить, пустит ли он $LOGIN"
  if [ -n "$deny_users" ] && printf ' %s ' "$deny_users" | grep -qF " $LOGIN "; then
    warn "в sshd $LOGIN запрещён через DenyUsers"
  fi
  return 0
}

# --- Отчёт о доступе Тимура -------------------------------------------------
access_report() {
  say "Доступ Тимура"
  if ! id "$LOGIN" >/dev/null 2>&1; then
    say "  пользователя $LOGIN нет"
    return
  fi
  local home; home="$(getent passwd "$LOGIN" | cut -d: -f6)"
  ok "пользователь $LOGIN есть, оболочка $(getent passwd "$LOGIN" | cut -d: -f7)"
  if grep -qF "$KEY_BODY" "$home/.ssh/authorized_keys" 2>/dev/null; then
    ok "его ключ стоит (aura-timur-20261004), всего ключей у него: $(count_keys "$home/.ssh/authorized_keys")"
  else
    warn "его ключа нет"
  fi
  if [ -f "$SUDOERS" ] && visudo -cf "$SUDOERS" >/dev/null 2>&1; then
    ok "права sudo: только ${TOOLS[*]}"
  else
    warn "правил sudo для него нет"
  fi
  local missing=""
  for t in "${TOOLS[@]}"; do [ -x "$TOOLS_DIR/$t" ] || missing="$missing $t"; done
  [ -z "$missing" ] && ok "команды на месте" || warn "нет команд:$missing"
  ok "ключей у root: было $ROOT_KEYS_BEFORE, сейчас $(count_keys /root/.ssh/authorized_keys)"
}

# ============================================================================
if [ "$MODE" = "--check" ]; then
  facts; ssh_report; access_report
  exit 0
fi

if [ "$MODE" = "--remove" ]; then
  say "Убираю доступ $LOGIN…"
  rm -f "$SUDOERS"
  for t in "${TOOLS[@]}"; do rm -f "$TOOLS_DIR/$t"; done
  if id "$LOGIN" >/dev/null 2>&1; then
    pkill -KILL -u "$LOGIN" 2>/dev/null || true
    userdel -r "$LOGIN" 2>/dev/null || userdel "$LOGIN"
  fi
  logger -t aura-access "доступ $LOGIN убран" 2>/dev/null || true
  ok "пользователь $LOGIN, его ключ и права sudo удалены; ключей у root: $(count_keys /root/.ssh/authorized_keys)"
  exit 0
fi

[ "$MODE" = "grant" ] || fail "Не знаю «$MODE». Можно: без слов, --check или --remove."

facts
ssh_report
say "Настраиваю…"

command -v sudo >/dev/null 2>&1 || fail "на сервере нет sudo — без него права не выдать"
command -v visudo >/dev/null 2>&1 || fail "на сервере нет visudo — без проверки правила sudo не ставлю"
if ! grep -qE '^[#@]includedir[[:space:]]+/etc/sudoers.d' /etc/sudoers 2>/dev/null; then
  fail "/etc/sudoers не читает /etc/sudoers.d — правило некуда положить, ничего не менял"
fi

# --- 1. Пользователь ---------------------------------------------------------
if id "$LOGIN" >/dev/null 2>&1; then
  ok "пользователь $LOGIN уже есть"
else
  useradd -m -s /bin/bash -c "Timur - AURA maintenance" "$LOGIN" || fail "не создал пользователя $LOGIN"
  ok "создан пользователь $LOGIN"
fi
# Пароля нет и не будет: вход только по ключу. «*» — не «заблокирован»:
# заблокированного («!») sshd без PAM не пускает и по ключу.
if [ "$(passwd -S "$LOGIN" 2>/dev/null | awk '{print $2}')" = "L" ]; then
  usermod -p '*' "$LOGIN"
fi
HOME_DIR="$(getent passwd "$LOGIN" | cut -d: -f6)"
[ -d "$HOME_DIR" ] || { mkdir -p "$HOME_DIR"; chown "$LOGIN:" "$HOME_DIR"; }
# sshd отказывает, если домашнюю папку могут менять другие.
chmod go-w "$HOME_DIR"

# --- 2. Ключ -----------------------------------------------------------------
install -d -m 700 -o "$LOGIN" -g "$(id -gn "$LOGIN")" "$HOME_DIR/.ssh"
AUTH="$HOME_DIR/.ssh/authorized_keys"
touch "$AUTH"
if grep -qF "$KEY_BODY" "$AUTH"; then
  ok "ключ Тимура уже стоит — второй раз не добавляю"
else
  # Файл мог кончаться без перевода строки — тогда ключ слипся бы с прежним.
  [ -s "$AUTH" ] && [ -n "$(tail -c1 "$AUTH")" ] && printf '\n' >> "$AUTH"
  printf '%s\n' "$KEY" >> "$AUTH"
  ok "ключ Тимура добавлен"
fi
chown "$LOGIN:" "$AUTH"; chmod 600 "$AUTH"

# --- 3. Команды --------------------------------------------------------------
# Каждая проверяет свои аргументы сама: sudo разрешает команду целиком, и
# всё, что она примет, будет выполнено от root.

write_tool() {  # имя, содержимое из stdin
  local tmp; tmp="$(mktemp)"
  cat > "$tmp"
  bash -n "$tmp" || { rm -f "$tmp"; fail "ошибка в $1 — ничего не ставлю"; }
  install -m 755 -o root -g root "$tmp" "$TOOLS_DIR/$1"
  rm -f "$tmp"
}

write_tool aura-service <<EOF
#!/bin/bash
# Служба AURA: состояние и перезапуск. Поставлено grant-timur.sh.
set -uo pipefail
export SYSTEMD_PAGER=cat PAGER=cat
S="$SERVICE"
case "\${1:-status}" in
  status)  exec systemctl --no-pager --full status "\$S" ;;
  restart|start|stop)
           systemctl "\$1" "\$S"; rc=\$?
           sleep 3
           systemctl --no-pager --full --lines=10 status "\$S"
           exit \$rc ;;
  timers)  exec systemctl --no-pager list-timers --all \\
             "\$S-update.timer" "\$S-watchdog.timer" "\$S-backup.timer" ;;
  *) echo "Как пользоваться: sudo aura-service status|restart|start|stop|timers"; exit 2 ;;
esac
EOF

write_tool aura-logs <<EOF
#!/bin/bash
# Журнал AURA. Поставлено grant-timur.sh.
# Аргументы принимаются только из короткого списка: у journalctl есть и
# такие, что стирают журнал или открывают просмотрщик с выходом в оболочку.
set -uo pipefail
export SYSTEMD_PAGER=cat PAGER=cat
S="$SERVICE"
usage() {
  echo "Как пользоваться: sudo aura-logs [-u bot|update|watchdog|backup] [-n 200] [-f]"
  echo "                  [--since '1 hour ago'] [--until …] [-p err] [-g текст] [-o short-iso|cat|json]"
  exit 2
}
unit="\$S"; args=(); lines=200
while [ \$# -gt 0 ]; do
  case "\$1" in
    -u|--unit)  [ \$# -ge 2 ] || usage
                case "\$2" in bot|"\$S") unit="\$S" ;; update|watchdog|backup) unit="\$S-\$2" ;; *) usage ;; esac
                shift ;;
    -n|--lines) [ \$# -ge 2 ] && [[ "\$2" =~ ^[0-9]{1,6}\$ ]] || usage; lines="\$2"; shift ;;
    -f|--follow) args+=(-f) ;;
    -r|--reverse) args+=(-r) ;;
    --since|--until) [ \$# -ge 2 ] && [[ "\$2" =~ ^[-0-9A-Za-z:\ .+]{1,40}\$ ]] || usage; args+=("\$1" "\$2"); shift ;;
    -p|--priority) [ \$# -ge 2 ] && [[ "\$2" =~ ^[a-z0-7.]{1,20}\$ ]] || usage; args+=(-p "\$2"); shift ;;
    -g|--grep)  [ \$# -ge 2 ] || usage; args+=(-g "\$2"); shift ;;
    -o|--output) [ \$# -ge 2 ] && [[ "\$2" =~ ^(short|short-iso|short-precise|cat|json|json-pretty|verbose)\$ ]] || usage
                args+=(-o "\$2"); shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
  shift
done
exec journalctl --no-pager -u "\$unit" -n "\$lines" "\${args[@]}"
EOF

write_tool aura-run <<EOF
#!/bin/bash
# Скрипты проекта AURA по имени. Поставлено grant-timur.sh.
# Имя сверяется со списком целиком: путь или «..» сюда не пройдут.
set -uo pipefail
APP_DIR="$APP_DIR"
ALLOWED="$SCRIPTS"
name="\${1:-}"
[[ "\$name" =~ ^[a-z-]{1,30}\$ ]] || name="-"
case " \$ALLOWED " in
  *" \$name "*) ;;
  *) name="-" ;;
esac
if [ "\$name" = "-" ]; then
  echo "Как пользоваться: sudo aura-run <скрипт> [аргументы]"
  echo "Можно: \$ALLOWED"
  exit 2
fi
[ -f "\$APP_DIR/\$name.sh" ] || { echo "Нет \$APP_DIR/\$name.sh"; exit 1; }
shift
cd "\$APP_DIR" || exit 1
exec /bin/bash "\$APP_DIR/\$name.sh" "\$@"
EOF

write_tool aura-git <<EOF
#!/bin/bash
# Какая версия AURA стоит на сервере. Поставлено grant-timur.sh.
# Без своих аргументов к git: у него есть и запись в файлы (--output), и
# просмотрщик с выходом в оболочку.
set -uo pipefail
export GIT_PAGER=cat PAGER=cat
cd "$APP_DIR" || exit 1
case "\${1:-status}" in
  status) git --no-pager status --short --branch
          echo; git --no-pager log --oneline -15 ;;
  log)    git --no-pager log --stat -15 ;;
  diff)   git --no-pager diff ;;
  *) echo "Как пользоваться: sudo aura-git status|log|diff"; exit 2 ;;
esac
EOF
ok "команды поставлены: ${TOOLS[*]}"

# --- 4. sudo -----------------------------------------------------------------
TMP_SUDO="$(mktemp)"
{
  echo "# AURA: обслуживание бота Тимуром. Поставлено grant-timur.sh."
  echo "# Убрать: bash grant-timur.sh --remove"
  printf 'Cmnd_Alias AURA_%s_TOOLS = ' "${LOGIN^^}"
  first=1
  for t in "${TOOLS[@]}"; do
    [ $first = 1 ] || printf ', '
    printf '%s/%s' "$TOOLS_DIR" "$t"; first=0
  done
  printf '\n%s ALL=(root) NOPASSWD: AURA_%s_TOOLS\n' "$LOGIN" "${LOGIN^^}"
} > "$TMP_SUDO"
if visudo -cf "$TMP_SUDO" >/dev/null; then
  install -m 440 -o root -g root "$TMP_SUDO" "$SUDOERS"
  rm -f "$TMP_SUDO"
  visudo -c >/dev/null || { rm -f "$SUDOERS"; fail "sudo после правки не проходит проверку — правило снял"; }
  ok "sudo: $LOGIN может только ${TOOLS[*]}"
else
  rm -f "$TMP_SUDO"
  fail "правило sudo не прошло проверку — ничего не поставил"
fi

# --- 5. Памятка в его домашней папке ----------------------------------------
cat > "$HOME_DIR/AURA.txt" <<EOF
Сервер AURA. Проект: $APP_DIR, служба: $SERVICE (работает от ${SERVICE_USER:-root}).

  sudo aura-service status|restart|start|stop|timers
  sudo aura-logs -n 200            (ещё: -f, --since '1 hour ago', -p err, -g текст,
                                    -u update|watchdog|backup)
  sudo aura-run status             (можно: $SCRIPTS)
  sudo aura-git status|log|diff

Код — на GitHub, ветка $(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?').
Сервер забирает её сам каждые 10 минут; сразу — sudo aura-run update.
Файлов проекта, .env и копий базы отсюда не видно — так задумано.
EOF
chown "$LOGIN:" "$HOME_DIR/AURA.txt"; chmod 644 "$HOME_DIR/AURA.txt"

logger -t aura-access "доступ $LOGIN выдан или обновлён (ключ aura-timur-20261004)" 2>/dev/null || true

# --- Итог --------------------------------------------------------------------
access_report
ROOT_KEYS_AFTER="$(count_keys /root/.ssh/authorized_keys)"
[ "$ROOT_KEYS_BEFORE" = "$ROOT_KEYS_AFTER" ] || warn "число ключей root изменилось — так быть не должно"

say ""
say "Готово. Для Тимура:  ssh -p ${SSH_PORT:-22} $LOGIN@$EXPECTED_IP"
