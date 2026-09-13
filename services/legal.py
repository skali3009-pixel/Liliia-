"""Правовые документы: оферта, политика данных, согласия.

Тексты лежат отдельными файлами в legal/, а реквизиты владельца подставляются
из настроек: так документ правится в одном месте и не расходится с тем, что
показывает бот.

Версия документов — дата их последнего изменения. Когда она меняется, бот
просит согласие заново: молча подменять условия, под которыми человек уже
согласился, нельзя.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import config

logger = logging.getLogger(__name__)

LEGAL_DIR = Path(__file__).resolve().parent.parent / "legal"

# Меняется вместе с текстами документов — тогда бот переспросит согласие.
LEGAL_VERSION = "05.09.2026"


@dataclass(frozen=True)
class Document:
    slug: str
    title: str
    eyebrow: str


DOCUMENTS: dict[str, Document] = {
    "offer": Document("offer", "Публичная оферта", "Условия использования"),
    "privacy": Document("privacy", "Политика обработки персональных данных", "Твои данные"),
    "consent": Document("consent", "Согласие на обработку персональных данных", "Согласие"),
    "marketing": Document("marketing", "Согласие на рекламную рассылку", "Реклама"),
}


def _placeholders() -> dict[str, str]:
    """Чем заменить метки в текстах документов."""
    bot = f"@{config.BOT_USERNAME}" if config.BOT_USERNAME else "«приложение питания»"
    return {
        "{{OWNER}}": config.LEGAL_OWNER,
        "{{REQUISITES}}": config.LEGAL_REQUISITES,
        "{{EMAIL}}": config.LEGAL_EMAIL,
        "{{BOT}}": bot,
        "{{VERSION}}": LEGAL_VERSION,
    }


def render(slug: str) -> str | None:
    """Готовая HTML-страница документа или None, если такого документа нет."""
    document = DOCUMENTS.get(slug)
    if document is None:
        return None

    body_path = LEGAL_DIR / f"{document.slug}.html"
    layout_path = LEGAL_DIR / "_layout.html"
    if not body_path.exists() or not layout_path.exists():
        logger.error("Не найден файл документа %s", body_path)
        return None

    page = layout_path.read_text(encoding="utf-8")
    page = page.replace("{{BODY}}", body_path.read_text(encoding="utf-8"))
    page = page.replace("{{TITLE}}", document.title).replace("{{EYEBROW}}", document.eyebrow)

    for mark, value in _placeholders().items():
        page = page.replace(mark, value)
    return page


def document_url(slug: str) -> str:
    """Публичная ссылка на документ."""
    base = (config.WEBAPP_URL or "").rstrip("/")
    return f"{base}/legal/{slug}"


def links_ready() -> bool:
    """Есть ли адрес, по которому документы вообще открываются."""
    return bool(config.WEBAPP_URL)
