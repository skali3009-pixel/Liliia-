"""Список команд в меню Telegram — той синей кнопки рядом с полем ввода.

Его не было вовсе, и это значит, что про /problem, /steps, /export и /delete
знал только тот, кому их назвали вслух. Команда, о которой нельзя узнать
изнутри бота, всё равно что не существует.

Два правила. Первое: список короткий. Telegram показывает его всплывающим
окном, и двадцать строк читаются не лучше, чем ноль. Сюда попадает только то,
чего нет на кнопках меню, и то, о чём человек обязан иметь возможность
узнать сам, — выгрузка и удаление данных.

Второе: хозяйские команды отдельно. /grant и /admin в общем списке — это
приглашение их потыкать, а объяснять каждому, почему у него не работает, —
лишний разговор. Telegram умеет показывать личный список конкретному чату,
им и пользуемся.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

import config

logger = logging.getLogger(__name__)

# Команды всем. Порядок — от частого к редкому: наверх смотрят чаще.
PUBLIC: tuple[tuple[str, str], ...] = (
    ("day", "Что я сегодня ела"),
    ("steps", "Записать шаги за сегодня"),
    ("sync", "Чтобы шаги приходили сами"),
    ("problem", "Что-то не так — рассказать"),
    ("preps", "Заготовки и сроки хранения"),
    ("export", "Выгрузить мои данные файлом"),
    ("legal", "Документы и согласия"),
    ("delete", "Удалить мои данные"),
    ("stop_ads", "Не присылать новости"),
    ("start", "Начать заново"),
)

# Показывается только при включённой оплате: в бесплатной бете строка про
# подписку заставляет человека гадать, что он купил.
PAID: tuple[tuple[str, str], ...] = (
    ("subscription", "Моя подписка"),
)

# Только владельцу, личным списком для его чата.
ADMIN: tuple[tuple[str, str], ...] = (
    ("admin", "Сводка по боту"),
    ("report", "Отчёт сейчас: день или неделя"),
    ("grant", "Выдать доступ человеку"),
    ("id", "Мой числовой номер"),
)


def public() -> list[tuple[str, str]]:
    """Что видят все."""
    return list(PUBLIC) + (list(PAID) if config.PAYWALL else [])


def admin() -> list[tuple[str, str]]:
    """Что видит владелец: всё общее плюс своё."""
    return public() + list(ADMIN)


def _commands(pairs) -> list[BotCommand]:
    return [BotCommand(command=name, description=text) for name, text in pairs]


async def apply(bot: Bot) -> None:
    """Записать списки в Telegram. Ошибка здесь не должна ронять запуск."""
    try:
        await bot.set_my_commands(_commands(public()), scope=BotCommandScopeDefault())
    except Exception:  # noqa: BLE001 — без меню бот работает как раньше
        logger.warning("Не удалось записать список команд", exc_info=True)
        return

    for owner in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(_commands(admin()),
                                      scope=BotCommandScopeChat(chat_id=owner))
        except Exception:  # noqa: BLE001 — владелец мог не начинать чат
            logger.info("Не удалось записать список команд владельцу %s", owner)

    logger.info("Список команд обновлён: %d общих", len(public()))


__all__ = ["ADMIN", "PAID", "PUBLIC", "admin", "apply", "public"]
