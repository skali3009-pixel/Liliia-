"""Простое файловое хранилище завода: песни, черновики, очередь публикаций.

Один пользователь, один процесс — поэтому обычные JSON-файлы, без базы.
Всё лежит в каталоге data/ рядом с ботом и переживает перезапуск.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

_SONGS_FILE = os.path.join(DATA_DIR, "songs.json")
_DRAFTS_FILE = os.path.join(DATA_DIR, "drafts.json")
_QUEUE_FILE = os.path.join(DATA_DIR, "queue.json")

# Запись в файл идёт из обработчиков разных апдейтов — сериализуем.
_lock = threading.Lock()

MSK = timezone(timedelta(hours=3))

# Каталог, с которого завод стартует. Припевы она добавляет через бота:
# без припева концепцию до кадров не довести, но список должен быть сразу.
_SEED_SONGS = [
    {"title": "Янымда бул", "lang": "tat"},
    {"title": "Исемең генә", "lang": "tat"},
    {"title": "Бәхет", "lang": "tat"},
    {"title": "Матурым", "lang": "tat"},
    {"title": "Я жива", "lang": "rus"},
    {"title": "Не вместо меня", "lang": "rus"},
    {"title": "Женщина PRIME", "lang": "rus"},
    {"title": "Живи сейчас", "lang": "rus"},
    {"title": "Плохая идея", "lang": "rus"},
    {"title": "Ай BONITO", "lang": "rus"},
    {"title": "Мурашки", "lang": "rus"},
    {"title": "Где ты", "lang": "rus"},
    {"title": "Доброе утро", "lang": "rus"},
    {"title": "Сердце сможет", "lang": "rus"},
]


def _read(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Битый файл не должен ронять бота — начинаем с пустого.
        return default


def _write(path: str, value) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # атомарно: не остаётся полузаписанного файла


# --- Песни -----------------------------------------------------------------

def list_songs() -> list[dict]:
    """Каталог песен. При первом обращении создаётся из зашитого списка."""
    with _lock:
        songs = _read(_SONGS_FILE, None)
        if songs is None:
            songs = [dict(s, id=str(i + 1), chorus="") for i, s in enumerate(_SEED_SONGS)]
            _write(_SONGS_FILE, songs)
        return songs


def get_song(song_id: str) -> dict | None:
    return next((s for s in list_songs() if s["id"] == song_id), None)


def set_chorus(song_id: str, chorus: str) -> bool:
    with _lock:
        songs = _read(_SONGS_FILE, [])
        for song in songs:
            if song["id"] == song_id:
                song["chorus"] = chorus.strip()
                _write(_SONGS_FILE, songs)
                return True
        return False


def add_song(title: str, lang: str, chorus: str = "") -> dict:
    with _lock:
        songs = _read(_SONGS_FILE, [])
        new_id = str(max((int(s["id"]) for s in songs), default=0) + 1)
        song = {"id": new_id, "title": title.strip(), "lang": lang, "chorus": chorus.strip()}
        songs.append(song)
        _write(_SONGS_FILE, songs)
        return song


# --- Черновики -------------------------------------------------------------
# Живут между нажатиями кнопок: сгенерировали варианты -> она выбирает.

def save_draft(chat_id: int, payload: dict) -> str:
    draft_id = uuid.uuid4().hex[:8]
    with _lock:
        drafts = _read(_DRAFTS_FILE, {})
        drafts[draft_id] = dict(payload, chat_id=chat_id,
                                created_at=datetime.now(timezone.utc).isoformat())
        # Не копим бесконечно: держим последние 50.
        if len(drafts) > 50:
            for key in sorted(drafts, key=lambda k: drafts[k]["created_at"])[:-50]:
                drafts.pop(key)
        _write(_DRAFTS_FILE, drafts)
    return draft_id


def get_draft(draft_id: str) -> dict | None:
    return _read(_DRAFTS_FILE, {}).get(draft_id)


# --- Очередь публикаций ----------------------------------------------------

def add_to_queue(item: dict) -> dict:
    with _lock:
        queue = _read(_QUEUE_FILE, [])
        item = dict(item, id=uuid.uuid4().hex[:8], status="ждёт",
                    added_at=datetime.now(timezone.utc).isoformat())
        queue.append(item)
        _write(_QUEUE_FILE, queue)
        return item


def list_queue(status: str | None = None) -> list[dict]:
    queue = _read(_QUEUE_FILE, [])
    if status:
        queue = [q for q in queue if q["status"] == status]
    return queue


def set_queue_status(item_id: str, status: str) -> bool:
    with _lock:
        queue = _read(_QUEUE_FILE, [])
        for item in queue:
            if item["id"] == item_id:
                item["status"] = status
                _write(_QUEUE_FILE, queue)
                return True
        return False


def now_msk() -> datetime:
    return datetime.now(MSK)
