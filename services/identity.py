"""Имя бота: от него зависят ссылки-приглашения.

Поломка здесь тихая и полная. Бот работает, экраны открываются, а кнопка
«Позвать» отвечает «ссылка появится, когда у бота будет имя» — то есть
позвать кого-нибудь нельзя вообще. Ломаются сразу и друзья, и команда, а
понять, что именно не так, человеку неоткуда.

Раньше имя надо было вписать в .env руками, и установщик этого не делал.
Спрашивать проще, чем требовать: бот знает своё имя сам.
"""

from __future__ import annotations

import logging

import config

logger = logging.getLogger(__name__)


async def learn_username(bot) -> str:
    """Узнать имя у Telegram, если в .env его нет. Возвращает то, что вышло."""
    if config.BOT_USERNAME:
        return config.BOT_USERNAME

    try:
        me = await bot.get_me()
    except Exception:  # noqa: BLE001 — без имени бот работает, просто без ссылок
        logger.warning("Не удалось узнать имя бота — ссылки-приглашения не работают",
                       exc_info=True)
        return ""

    username = (getattr(me, "username", "") or "").lstrip("@")
    if username:
        config.BOT_USERNAME = username
        logger.info("Имя бота: @%s (ссылки-приглашения работают)", username)
    return config.BOT_USERNAME


__all__ = ["learn_username"]
