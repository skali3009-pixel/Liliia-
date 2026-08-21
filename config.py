"""Загрузка настроек бота из переменных окружения (.env)."""

import os

from dotenv import load_dotenv

load_dotenv()


def _get_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            f"Скопируйте .env.example в .env и заполните значения."
        )
    return value


# Токен Telegram-бота, выданный @BotFather.
BOT_TOKEN = _get_required("BOT_TOKEN")

# Ключ Anthropic API (console.anthropic.com -> API Keys).
ANTHROPIC_API_KEY = _get_required("ANTHROPIC_API_KEY")

# Модель Claude, которую использует бот. По умолчанию — самая мощная (Opus 5).
# Для более дешёвого и быстрого варианта можно поставить "claude-haiku-4-5".
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")

# Системный промпт — задаёт "личность" и поведение бота.
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты — дружелюбный ассистент в Telegram. Отвечай кратко, ясно и по делу, "
    "если пользователь не просит подробностей.",
)

# Сколько последних сообщений из истории диалога отправлять модели.
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))

# Максимальная длина ответа модели в токенах.
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
