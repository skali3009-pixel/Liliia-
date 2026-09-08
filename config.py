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
# Модель для распознавания еды по фото. Sonnet справляется с «что на тарелке
# и сколько это весит» практически как Opus, а стоит в 2,5 раза дешевле —
# на фото это основная статья расходов.
VISION_MODEL = os.getenv("VISION_MODEL", "claude-sonnet-5")
# Модель для сборки блюда по методу нутрициолога: там важнее рассуждение,
# а вызовов на порядок меньше, чем распознаваний фото.
BUILD_MODEL = os.getenv("BUILD_MODEL", "claude-opus-5")

# --- Пределы расходов ------------------------------------------------------
# Сколько долларов в сутки бот имеет право потратить на распознавание.
# Дойдя до потолка, он перестаёт распознавать фото и пишет владельцу, но
# всё остальное продолжает работать.
DAILY_COST_LIMIT_USD = float(os.getenv("DAILY_COST_LIMIT_USD", "20"))
# Сколько распознаваний в сутки доступно одному человеку. Обычному хватает
# с запасом; защищает от случайной пачки в двести фото.
PHOTO_LIMIT_PER_DAY = int(os.getenv("PHOTO_LIMIT_PER_DAY", "15"))

# --- Пределы диска ---------------------------------------------------------
# При таком заполнении диска предупреждаем владельца, при следующем —
# перестаём принимать новые фото, чтобы не остановить запись в базу.
DISK_WARN_PERCENT = int(os.getenv("DISK_WARN_PERCENT", "80"))
DISK_STOP_PERCENT = int(os.getenv("DISK_STOP_PERCENT", "90"))

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

# --- Правовые документы -----------------------------------------------------
# Подставляются в оферту и политику данных. Без них документы выйдут с
# пустыми реквизитами, поэтому бот предупредит владельца при старте.
LEGAL_OWNER = os.getenv("LEGAL_OWNER", "")
LEGAL_REQUISITES = os.getenv("LEGAL_REQUISITES", "")
LEGAL_EMAIL = os.getenv("LEGAL_EMAIL", "")
# Имя бота без @ — нужно для ссылок и текста документов.
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")

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

# Платный доступ включается только явно — строкой PAYWALL=1 в .env.
# По умолчанию бот бесплатен для всех: пока он дорабатывается, люди приходят
# и пользуются им бесплатно, и оплата не должна включиться сама собой, побочным
# эффектом какой-то другой настройки (раньше её включало появление ADMIN_IDS —
# то есть попытка получать отчёты о сбоях заодно закрывала бота от людей).
# ADMIN_IDS при этом всё равно обязателен: иначе владелец закроет бота от себя
# же и не сможет ни выдать доступ, ни посмотреть статистику.
PAYWALL = os.getenv("PAYWALL", "0").lower() in {"1", "true", "yes", "on"} and bool(ADMIN_IDS)

# --- Экономика: сходится ли подписка с расходами -----------------------------
# Сколько владелец реально получает за одну звезду Telegram, в долларах.
# Telegram удерживает свою долю, поэтому «499 звёзд» и «499 × цена звезды
# для покупателя» — разные деньги. Значение уточняется в кабинете выплат;
# по умолчанию — консервативная оценка, чтобы отчёт не рисовал лишнего.
STAR_USD = float(os.getenv("STAR_USD", "0.013"))

# Постоянные расходы в месяц, доллары: сервер, домен, бухгалтерия, всё, что
# платится независимо от числа людей. Пока не заполнено, отчёт честно пишет,
# что считает только расход на модель, и не делает вид, что знает прибыль.
FIXED_COSTS_USD = float(os.getenv("FIXED_COSTS_USD", "0"))

# Налог с выручки, проценты. 0 — пока не оформлено.
TAX_PERCENT = float(os.getenv("TAX_PERCENT", "0"))

# Счёт нажатий кнопок меню в чате. Заведён на время испытаний: без него
# «этой кнопкой не пользуются» — догадка одного человека, а не факт.
# Выключается: bash set-buttons.sh off
BUTTON_STATS = os.getenv("BUTTON_STATS", "1") not in {"0", "false", "no", "off"}

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
