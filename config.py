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

# Модель для распознавания еды по фото (vision). По умолчанию — Opus 5.
# Можно поставить более дешёвую/быструю, например "claude-sonnet-5".
VISION_MODEL = os.getenv("VISION_MODEL", "claude-opus-5")

# Строка подключения к PostgreSQL (профиль пользователя, питание,
# тренировки, прогресс). Формат — SQLAlchemy + asyncpg.
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/nutrition_bot"
)
