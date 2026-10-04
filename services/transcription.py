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

    async def ask(response_format: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            return await client.post(
                url,
                headers={"Authorization": f"Bearer {config.VOICE_API_KEY}"},
                files={"file": (filename, audio, "audio/ogg")},
                data={
                    "model": config.VOICE_MODEL,
                    # Явный язык заметно повышает точность на коротких записях.
                    "language": "ru",
                    "response_format": response_format,
                },
            )

    # Подробный ответ несёт для каждого куска записи вероятность, что речи
    # там нет. По ней и отличаем тишину: на ней Whisper часто не молчит, а
    # выдумывает фразу («Продолжение следует…»), и бот принимал её за речь.
    # Не всякий сервис такой формат понимает — тогда спрашиваем по-старому.
    response = await ask("verbose_json")
    if response.status_code == 400:
        logger.info("Сервис речи не принял verbose_json: %s", response.text[:200])
        response = await ask("json")

    if response.status_code != 200:
        logger.warning("Whisper вернул %s: %s", response.status_code, response.text[:300])
        raise TranscriptionError("Сервис распознавания речи не ответил. Попробуй ещё раз.")

    payload = response.json()
    text = str(payload.get("text", "")).strip()
    if not text or _only_silence(payload):
        raise TranscriptionError(NOT_HEARD)
    return text


# Тот же ответ, что и раньше на пустую расшифровку: «не расслышал» — это
# про запись, а не про блюдо.
NOT_HEARD = "Не расслышал. Запиши ещё раз, чуть ближе к микрофону."

# Порог Whisper: выше него кусок записи считается не речью. 0,6 — значение,
# которое сам Whisper использует для отсева тишины.
NO_SPEECH = 0.6


def _only_silence(payload: dict) -> bool:
    """Все куски записи похожи на тишину или шум, а не на речь."""
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        return False          # подробностей нет — судим только по тексту
    chances = [s.get("no_speech_prob") for s in segments if isinstance(s, dict)]
    chances = [c for c in chances if isinstance(c, (int, float))]
    return bool(chances) and min(chances) >= NO_SPEECH
