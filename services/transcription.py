"""Расшифровка голосовых сообщений (Whisper).

У Anthropic нет API для распознавания речи, поэтому используется отдельный
сервис с OpenAI-совместимым endpoint'ом `/audio/transcriptions`: по умолчанию
Groq (бесплатный уровень), но подойдёт и OpenAI — достаточно поменять
VOICE_BASE_URL и ключ в .env.
"""

from __future__ import annotations

import logging

import httpx

import config

logger = logging.getLogger(__name__)

# Голосовые сообщения Telegram короткие, но сеть бывает медленной.
TIMEOUT_SECONDS = 60.0

# Ограничение Whisper-сервисов на размер файла.
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class TranscriptionError(Exception):
    """Не удалось расшифровать голосовое сообщение."""


class VoiceNotConfigured(TranscriptionError):
    """Не задан ключ для распознавания речи."""


async def transcribe(audio: bytes, *, filename: str = "voice.ogg") -> str:
    """Вернуть текст голосового сообщения."""
    if not config.VOICE_API_KEY:
        raise VoiceNotConfigured(
            "Голосовые сообщения пока не настроены: нужен ключ для распознавания речи.\n\n"
            "Пока можно написать текстом — например: «дошик с маслом и яйцом»."
        )

    if len(audio) > MAX_AUDIO_BYTES:
        raise TranscriptionError("Голосовое слишком длинное — запиши покороче.")

    url = f"{config.VOICE_BASE_URL.rstrip('/')}/audio/transcriptions"

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {config.VOICE_API_KEY}"},
            files={"file": (filename, audio, "audio/ogg")},
            data={
                "model": config.VOICE_MODEL,
                # Явный язык заметно повышает точность на коротких записях.
                "language": "ru",
                "response_format": "json",
            },
        )

    if response.status_code != 200:
        logger.warning("Whisper вернул %s: %s", response.status_code, response.text[:300])
        raise TranscriptionError("Сервис распознавания речи не ответил. Попробуй ещё раз.")

    text = str(response.json().get("text", "")).strip()
    if not text:
        raise TranscriptionError("Не расслышал. Запиши ещё раз, чуть ближе к микрофону.")
    return text
