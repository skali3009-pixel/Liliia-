"""Existing public destinations for the product interface."""

import re

import config
from services.legal import DOCUMENTS, document_url, links_ready
from services.identity import start_link


def public_links() -> dict:
    username = config.BOT_USERNAME or ""
    valid = bool(re.fullmatch(r"[A-Za-z0-9_]{5,32}", username))
    return {
        "chat_food_url": start_link("add_food") if valid else "",
        "music_url": config.MUSIC_URL or "",
        "documents": [{"title": doc.title, "url": document_url(doc.slug)}
                      for doc in DOCUMENTS.values()] if links_ready() else [],
        "access_label": "Действуют текущие условия доступа. Новые продажи пока не подключены.",
    }
