"""Загрузка настроек бота из переменных окружения (.env)."""

import os
from pathlib import Path

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
# Необязателен: без него бот работает, но распознавание еды по фото
# недоступно — это единственная функция, которая обращается к Claude.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Модель для распознавания еды по фото (vision). По умолчанию — Opus 5.
# Можно поставить более дешёвую/быструю, например "claude-sonnet-5".
VISION_MODEL = os.getenv("VISION_MODEL", "claude-opus-5")

# Распознавание голосовых сообщений (Whisper). У Anthropic такого API нет,
# поэтому используется совместимый с OpenAI endpoint. По умолчанию — Groq:
# у него есть бесплатный уровень. Подойдёт и сам OpenAI (см. VOICE_BASE_URL).
VOICE_API_KEY = os.getenv("VOICE_API_KEY", "")
VOICE_BASE_URL = os.getenv("VOICE_BASE_URL", "https://api.groq.com/openai/v1")
VOICE_MODEL = os.getenv("VOICE_MODEL", "whisper-large-v3")

# Мини-приложение внутри Telegram. WEBAPP_URL — публичный адрес с HTTPS,
# который выдаёт setup-webapp.sh; пока он пуст, приложение не подключается
# и бот работает как обычно.
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
# Подпись кнопки мини-приложения рядом с полем ввода в чате.
WEBAPP_BUTTON = os.getenv("WEBAPP_BUTTON", "Кабинет")[:16]

# --- Платный доступ ---------------------------------------------------------
# Кто владеет ботом: у этих людей доступ всегда, им же приходит /admin.
ADMIN_IDS = {
    int(part) for part in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if part
}

# Сколько дней бесплатного знакомства даётся новому человеку.
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))

# Цена месяца в звёздах Telegram и длительность оплаченного периода.
# 30 дней — единственный период, который Telegram умеет списывать сам.
SUB_PRICE_STARS = int(os.getenv("SUB_PRICE_STARS", "499"))
SUB_PERIOD_DAYS = 30

# Платный доступ можно выключить: тогда бот открыт всем, как раньше.
PAYWALL = os.getenv("PAYWALL", "1") not in {"0", "false", "no"}

# Бот сам подтягивает обновления из git. Выключается AUTO_UPDATE=0.
AUTO_UPDATE = os.getenv("AUTO_UPDATE", "1") not in {"0", "false", "no"}
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "127.0.0.1")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8080"))

# Куда складывать фото прогресса, загруженные из приложения.
PHOTOS_DIR = os.getenv("PHOTOS_DIR", str(Path(__file__).parent / "data" / "photos"))

# Строка подключения к PostgreSQL (профиль пользователя, питание,
# тренировки, прогресс). Формат — SQLAlchemy + asyncpg.
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/nutrition_bot"
)
