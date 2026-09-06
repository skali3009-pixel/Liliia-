"""Что происходит, когда что-то ломается.

Раньше — ничего. Ошибка уходила в лог, человек оставался с тишиной вместо
ответа, владелец не узнавал ничего. Именно так несколько дней прожила
поломка, из-за которой еда из чата не сохранялась вовсе.

Теперь у поломки есть два адресата. Человеку — честный короткий ответ:
сломалось у нас, твои записи целы. Владельцу — где именно сломалось.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import ErrorEvent
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.feedback import CB_TELL
from services import crashes

logger = logging.getLogger(__name__)

# Ни трассировки, ни названий файлов: человеку они бесполезны, а испугать
# могут. Зато сказано главное — данные целы и виноват не он.
USER_TEXT = (
    "😔 Что-то сломалось на моей стороне — не у тебя.\n\n"
    "Я уже сообщил об этом хозяйке бота. Твои записи целы, ничего не "
    "потерялось. Попробуй ещё раз через минуту."
)


def _tell_button():
    """Что человек делал перед поломкой, знает только он сам.

    Сообщение о поломке говорит, что сломалось, но не что человек пытался
    сделать. Кнопка здесь стоит потому, что это и есть тот единственный
    момент, когда рассказать и легко, и есть о чём.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Рассказать, что я делала", callback_data=CB_TELL)
    return builder.as_markup()


def _person(update) -> tuple[int | None, object, object]:
    """Кому отвечать: сообщение или нажатая кнопка, если они вообще есть."""
    message = getattr(update, "message", None) or getattr(update, "edited_message", None)
    callback = getattr(update, "callback_query", None)
    holder = message or getattr(callback, "message", None)
    user = getattr(message, "from_user", None) or getattr(callback, "from_user", None)
    return (getattr(user, "id", None), holder, callback)


async def on_error(event: ErrorEvent, bot: Bot | None = None) -> bool:
    """Единая точка на все падения в чате.

    Возвращает True: ошибка обработана, дальше её нести некуда.
    """
    error = event.exception
    user_id, holder, callback = _person(getattr(event, "update", None))

    # Сначала человек, потом владелец: ответ важнее отчёта.
    if callback is not None:
        try:
            # Иначе кнопка так и останется с крутящимся индикатором.
            await callback.answer()
        except Exception:  # noqa: BLE001
            logger.info("Не удалось закрыть индикатор кнопки")
    if holder is not None:
        try:
            await holder.answer(USER_TEXT, reply_markup=_tell_button())
        except Exception:  # noqa: BLE001 — человек мог заблокировать бота
            logger.info("Не удалось ответить человеку о поломке")

    await crashes.report(bot, error, where="чат", user_id=user_id)
    return True
