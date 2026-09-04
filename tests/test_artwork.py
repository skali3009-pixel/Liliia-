"""Тесты автоскачивания фоновых артов (services/artwork.py)."""

import asyncio

from services import artwork
from services.artwork import ARTWORK, MIN_BYTES, ensure_artwork, missing

BIG_ENOUGH = b"x" * (MIN_BYTES + 1)


def test_all_art_names_are_known_and_unique():
    """Имена файлов зашиты в CSS — список не должен разъезжаться."""
    assert set(ARTWORK) == {"hero.png", "world.png", "moment.png", "sky.png", "gym.png"}
    assert len(set(ARTWORK.values())) == len(ARTWORK)


def test_missing_lists_everything_on_empty_folder(tmp_path):
    assert sorted(missing(tmp_path)) == sorted(ARTWORK)


def test_existing_file_is_not_reported_missing(tmp_path):
    (tmp_path / "hero.png").write_bytes(BIG_ENOUGH)
    assert "hero.png" not in missing(tmp_path)


def test_truncated_file_counts_as_missing(tmp_path):
    """Оборвавшаяся закачка не должна выдавать себя за картинку."""
    (tmp_path / "hero.png").write_bytes(b"broken")
    assert "hero.png" in missing(tmp_path)


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    async def read(self):
        return self._body


class _FakeSession:
    """Подменяет aiohttp: считает запросы и отдаёт заготовленное тело."""

    def __init__(self, body=BIG_ENOUGH):
        self.body = body
        self.requested: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url):
        self.requested.append(url)
        return _FakeResponse(self.body)


def run_ensure(monkeypatch, tmp_path, *, body=BIG_ENOUGH, force=False):
    session = _FakeSession(body)
    monkeypatch.setattr(artwork.aiohttp, "ClientSession", lambda **kwargs: session)
    downloaded = asyncio.run(ensure_artwork(force=force, directory=tmp_path))
    return session, downloaded


def test_downloads_everything_into_an_empty_folder(monkeypatch, tmp_path):
    session, downloaded = run_ensure(monkeypatch, tmp_path)

    assert sorted(downloaded) == sorted(ARTWORK)
    assert len(session.requested) == len(ARTWORK)
    assert (tmp_path / "hero.png").read_bytes() == BIG_ENOUGH


def test_already_downloaded_art_is_not_fetched_again(monkeypatch, tmp_path):
    for name in ARTWORK:
        (tmp_path / name).write_bytes(BIG_ENOUGH)

    session, downloaded = run_ensure(monkeypatch, tmp_path)

    assert downloaded == []
    assert session.requested == []


def test_force_refetches_everything(monkeypatch, tmp_path):
    for name in ARTWORK:
        (tmp_path / name).write_bytes(BIG_ENOUGH)

    session, downloaded = run_ensure(monkeypatch, tmp_path, force=True)

    assert len(session.requested) == len(ARTWORK)
    assert sorted(downloaded) == sorted(ARTWORK)


def test_short_answer_does_not_replace_a_good_file(monkeypatch, tmp_path):
    """CDN может ответить страницей с ошибкой — она не должна лечь как арт."""
    session, downloaded = run_ensure(monkeypatch, tmp_path, body=b"<html>error</html>")

    assert downloaded == []
    assert not (tmp_path / "hero.png").exists()
    assert not list(tmp_path.glob("*.part"))


def test_network_failure_is_survivable(monkeypatch, tmp_path):
    class _FailingSession(_FakeSession):
        def get(self, url):
            raise artwork.aiohttp.ClientError("нет сети")

    session = _FailingSession()
    monkeypatch.setattr(artwork.aiohttp, "ClientSession", lambda **kwargs: session)

    # Бот не должен падать из-за картинок: ошибка сети — это пустой результат.
    assert asyncio.run(ensure_artwork(directory=tmp_path)) == []
