"""Тесты автоскачивания фоновых артов (services/artwork.py)."""

import asyncio

from services import artwork
from services.artwork import ARTWORK, MIN_BYTES, ensure_artwork, missing

BIG_ENOUGH = b"x" * (MIN_BYTES + 1)


def lay_out(folder, *, sources=True):
    """Разложить арты по папке так, как это делает настоящее скачивание.

    С запиской о том, откуда каждый взят: без неё файл считается устаревшим,
    и в этом весь смысл записки.
    """
    import json

    for name in ARTWORK:
        (folder / name).write_bytes(BIG_ENOUGH)
    if sources:
        (folder / artwork.MANIFEST).write_text(
            json.dumps(dict(ARTWORK)), encoding="utf-8")


def test_all_art_names_are_known_and_unique():
    """Имена файлов зашиты в CSS — список не должен разъезжаться."""
    assert set(ARTWORK) == {"hero.png", "world.png", "moment.png", "sky.png",
                            "gym.png", "food.png"}
    assert len(set(ARTWORK.values())) == len(ARTWORK)


def test_every_art_is_actually_used_by_the_styles():
    """Скачанная и никем не показанная картинка — это просто занятое место."""
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "webapp" / "static" /
           "styles.css").read_text(encoding="utf-8")
    for name in ARTWORK:
        assert f"/static/img/{name}" in css, name


def test_missing_lists_everything_on_empty_folder(tmp_path):
    assert sorted(missing(tmp_path)) == sorted(ARTWORK)


def test_existing_file_is_not_reported_missing(tmp_path):
    lay_out(tmp_path)
    assert "hero.png" not in missing(tmp_path)


def test_a_replaced_picture_is_actually_replaced(tmp_path):
    """Смена ссылки в коде обязана менять картинку на сервере.

    Раньше не меняла: файл лежит на месте и нужного размера — проверка
    довольна, и на экране до конца времён оставалась старая картинка.
    Понять это можно было только глазами, и то если помнишь, как выглядела
    новая.
    """
    lay_out(tmp_path)
    assert missing(tmp_path) == []

    import json

    записка = json.loads((tmp_path / artwork.MANIFEST).read_text(encoding="utf-8"))
    записка["gym.png"] = "https://example.test/старая-картинка.png"
    (tmp_path / artwork.MANIFEST).write_text(json.dumps(записка), encoding="utf-8")

    assert missing(tmp_path) == ["gym.png"]


def test_art_from_before_the_manifest_is_refetched_once(tmp_path):
    """На сервере уже лежат картинки, скачанные до появления записки.

    Про них неизвестно, откуда они, — значит, они могут быть любыми.
    Перекачиваем один раз, и дальше записка есть.
    """
    lay_out(tmp_path, sources=False)
    assert sorted(missing(tmp_path)) == sorted(ARTWORK)


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
    lay_out(tmp_path)

    session, downloaded = run_ensure(monkeypatch, tmp_path)

    assert downloaded == []
    assert session.requested == []


def test_force_refetches_everything(monkeypatch, tmp_path):
    lay_out(tmp_path)

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


def test_the_report_does_not_confuse_a_missing_picture_with_an_old_one(monkeypatch, tmp_path):
    """Это два разных случая, и на экране они выглядят по-разному.

    Нет файла — на его месте соседний арт или градиент. Файл устарел — там
    не пусто, там прежняя картинка. Один текст на оба случая советовал бы
    не то и сбивал с толку.
    """
    import json

    from services import status

    lay_out(tmp_path)
    (tmp_path / "sky.png").unlink()
    записка = json.loads((tmp_path / artwork.MANIFEST).read_text(encoding="utf-8"))
    записка["gym.png"] = "https://example.test/прошлая.png"
    (tmp_path / artwork.MANIFEST).write_text(json.dumps(записка), encoding="utf-8")

    monkeypatch.setattr(artwork, "ART_DIR", tmp_path)
    text = "\n".join(status._art_lines())

    assert "не хватает 1" in text and "sky.png" in text
    assert "устарели 1" in text and "gym.png" in text
    assert "bash fetch-art.sh" in text


def test_the_report_stays_quiet_when_everything_is_current(monkeypatch, tmp_path):
    lay_out(tmp_path)
    monkeypatch.setattr(artwork, "ART_DIR", tmp_path)

    from services import status

    assert status._art_lines() == ["🖼 Картинки: все на месте"]
