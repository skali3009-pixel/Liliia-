# Telegram-бот на Claude

AI-ассистент для Telegram: пишете боту сообщение — он отвечает с помощью
модели Claude (Anthropic). Помнит контекст диалога в рамках чата.

Дополнительно есть команда **/audit** — она подключается к Instagram через
Composio, забирает реальные данные аккаунта (профиль, метрики за 30 дней,
последние посты) и присылает готовый PDF-аудит личного бренда.

## Что понадобится

1. **Токен бота** от [@BotFather](https://t.me/BotFather) — он у вас уже есть.
2. **API-ключ Anthropic** — получить на https://console.anthropic.com/settings/keys
   (нужна регистрация; у новых аккаунтов обычно есть небольшой бесплатный лимit
   для старта, дальше — по мере использования, привязка карты).
3. Python 3.10+.
4. *(Только для команды /audit)* аккаунт на [app.composio.dev](https://app.composio.dev)
   и Instagram **Business или Creator**-аккаунт, привязанный к Facebook-странице
   (обычный личный Instagram не поддерживается Instagram Graph API).

## Шаг 1. Установка зависимостей

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Шаг 2. Настройка секретов

```bash
cp .env.example .env
```

Откройте `.env` в редакторе и впишите:

```
BOT_TOKEN=ваш_токен_от_BotFather
ANTHROPIC_API_KEY=ваш_ключ_с_console.anthropic.com
```

Файл `.env` не попадёт в git (он уже в `.gitignore`) — никогда не публикуйте
токены в коде или в открытых репозиториях.

## Шаг 3. Запуск локально (проверить, что всё работает)

```bash
python bot.py
```

В консоли появится `Бот запускается...`. Откройте своего бота в Telegram и
напишите ему что-нибудь — должен прийти ответ от Claude. Команда `/reset`
очищает историю диалога. Остановить бота — `Ctrl+C`.

Пока в терминале запущен `bot.py`, бот работает. Если закрыть терминал —
бот перестанет отвечать. Чтобы он работал постоянно (24/7), нужен сервер —
см. следующий шаг.

## Шаг 4. Запуск на сервере (VPS) для работы 24/7

1. Арендуйте VPS (например, Ubuntu 22.04/24.04) у любого провайдера.
2. Скопируйте на сервер файлы проекта (`git clone` вашего репозитория или
   `scp`).
3. На сервере выполните шаги 1–2 из этого README (venv, зависимости, `.env`).
4. Настройте автозапуск через systemd — в репозитории есть готовый шаблон
   `telegram-bot.service`:

   ```bash
   sudo cp telegram-bot.service /etc/systemd/system/
   # отредактируйте пути (User, WorkingDirectory, ExecStart) под свой сервер
   sudo systemctl daemon-reload
   sudo systemctl enable --now telegram-bot
   ```

5. Проверить статус и логи:

   ```bash
   sudo systemctl status telegram-bot
   sudo journalctl -u telegram-bot -f
   ```

Теперь бот будет работать постоянно и автоматически перезапускаться при сбое
или перезагрузке сервера.

## Шаг 5. Настройка Instagram-аудита (команда /audit, необязательно)

1. На сервере установите системный шрифт с кириллицей (для генерации PDF):

   ```bash
   sudo apt install -y fonts-dejavu-core
   ```

2. Зарегистрируйтесь на [app.composio.dev](https://app.composio.dev) и создайте
   API-ключ: Settings -> API Keys. Впишите его в `.env`:

   ```
   COMPOSIO_API_KEY=ваш_ключ_с_app.composio.dev
   ```

3. В том же интерфейсе Composio: Connected Accounts -> Instagram -> Connect,
   авторизуйтесь через Facebook и подтвердите доступ к вашей Business/Creator-
   странице. Подключение сохраняется на стороне Composio — боту не нужно
   ничего дополнительно настраивать, он найдёт его сам.

4. Перезапустите бота (`sudo systemctl restart telegram-bot` на сервере, или
   заново `python bot.py` локально) и напишите ему `/audit`.

Бот соберёт данные, попросит Claude их проанализировать и через 30–60 секунд
пришлёт PDF с разбором профиля, топ-постами, стратегией по контенту и планом
на 90 дней.

**Если что-то пошло не так:**
- «Нет активного подключения Instagram» — переподключите аккаунт в
  Connected Accounts на app.composio.dev (шаг 3).
- «Не найден шрифт с поддержкой кириллицы» — выполните шаг 1.
- Личный (не Business/Creator) аккаунт Instagram не поддерживается — это
  ограничение самого Instagram Graph API, не бота.

## Настройки (необязательно)

Всё в `.env`, можно раскомментировать и поменять:

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `CLAUDE_MODEL` | `claude-opus-5` | Модель Claude. Для более дешёвых/быстрых ответов можно поставить `claude-haiku-4-5`. |
| `SYSTEM_PROMPT` | дружелюбный ассистент | "Личность" и инструкции для бота. |
| `MAX_HISTORY_MESSAGES` | `20` | Сколько последних сообщений диалога помнит бот. |
| `MAX_TOKENS` | `2048` | Максимальная длина одного ответа. |
| `COMPOSIO_API_KEY` | — | Ключ Composio для команды /audit (см. шаг 5). |

## Структура проекта

- `bot.py` — точка входа, обработка сообщений Telegram.
- `claude_client.py` — обращение к Claude API и история диалогов.
- `config.py` — чтение настроек из `.env`.
- `composio_instagram.py` — сбор данных Instagram через Composio API.
- `instagram_audit.py` — анализ данных через Claude (команда /audit).
- `report_pdf.py` — сборка PDF-отчёта из результатов аудита.
- `telegram-bot.service` — шаблон systemd-юнита для VPS.
