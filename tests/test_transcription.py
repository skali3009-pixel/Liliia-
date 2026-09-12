"""Тесты расшифровки голосовых сообщений."""

import asyncio

import pytest

from services import transcription
from services.transcription import TranscriptionError, VoiceNotConfigured, transcribe

AUDIO = b"OggS-fake-voice-bytes"


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Подменяет httpx.AsyncClient: запоминает запрос и отдаёт готовый ответ."""

    def __init__(self, response, captured: dict):
        self._response = response
        self._captured = captured

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self._captured["url"] = url
        self._captured.update(kwargs)
        return self._response


def _mock_http(monkeypatch, response, captured: dict):
    monkeypatch.setattr(transcription.httpx, "AsyncClient", _FakeAsyncClient(response, captured))
    monkeypatch.setattr(transcription.config, "VOICE_API_KEY", "gsk_test")


def test_transcribe_returns_recognized_text(monkeypatch):
    captured: dict = {}
    _mock_http(monkeypatch, _FakeResponse(payload={"text": "  дошик с яйцом  "}), captured)

    assert asyncio.run(transcribe(AUDIO)) == "дошик с яйцом"


def test_transcribe_sends_audio_and_model(monkeypatch):
    captured: dict = {}
    _mock_http(monkeypatch, _FakeResponse(payload={"text": "борщ"}), captured)
    monkeypatch.setattr(transcription.config, "VOICE_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(transcription.config, "VOICE_MODEL", "whisper-large-v3")

    asyncio.run(transcribe(AUDIO))

    assert captured["url"] == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert captured["headers"]["Authorization"] == "Bearer gsk_test"
    assert captured["files"]["file"][1] == AUDIO
    assert captured["data"]["model"] == "whisper-large-v3"
    assert captured["data"]["language"] == "ru"


def test_transcribe_requires_key(monkeypatch):
    monkeypatch.setattr(transcription.config, "VOICE_API_KEY", "")

    with pytest.raises(VoiceNotConfigured, match="не настроены"):
        asyncio.run(transcribe(AUDIO))


def test_transcribe_reports_service_error(monkeypatch):
    captured: dict = {}
    _mock_http(monkeypatch, _FakeResponse(status_code=401, text="unauthorized"), captured)

    with pytest.raises(TranscriptionError, match="не ответил"):
        asyncio.run(transcribe(AUDIO))


def test_transcribe_rejects_empty_result(monkeypatch):
    captured: dict = {}
    _mock_http(monkeypatch, _FakeResponse(payload={"text": "   "}), captured)

    with pytest.raises(TranscriptionError, match="Не расслышал"):
        asyncio.run(transcribe(AUDIO))


def test_transcribe_rejects_oversized_audio(monkeypatch):
    monkeypatch.setattr(transcription.config, "VOICE_API_KEY", "gsk_test")

    with pytest.raises(TranscriptionError, match="слишком длинное"):
        asyncio.run(transcribe(b"x" * (transcription.MAX_AUDIO_BYTES + 1)))
