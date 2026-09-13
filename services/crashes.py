"""Поломки: чтобы о них узнавали от бота, а не от человека.

История, ради которой это написано. Из `save_meal` убрали параметр вместе с
колонкой, а вызов в обработчике остался. С этой минуты ни одна еда из чата
не сохранялась: человек нажимал «Сохранить», и не происходило ничего.
Ошибка легла в лог, куда никто не смотрит; бот молчал, владелец молчал.
Узнали от живой девочки через несколько дней.

Значит, нужны две вещи, которых не было. Человеку — честный ответ вместо
тишины: сломалось у нас, твои записи целы. Владельцу — сообщение с местом
поломки, сразу.

И одно ограничение, без которого выйдет хуже, чем было: поломка в частом
месте повторяется десятки раз в минуту. Сигнал, приходящий пачками, через
день перестают читать. Поэтому про одну и ту же поломку сообщаем один раз
в полчаса, а общий часовой лимит сигналов — тот же, что у остальных.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot

import config
from services import alerts

logger = logging.getLogger(__name__)

# Корень проекта: по нему отличаем свой код от чужого в трассировке.
ROOT = Path(__file__).resolve().parent.parent

# Про одну и ту же поломку — не чаще одного раза за это время.
COOLDOWN = timedelta(minutes=30)

# Сколько разных поломок помним. Больше и не нужно: это защита от того,
# чтобы словарь не рос бесконечно на сыплющихся ошибках.
MAX_KINDS = 200

_seen: dict[str, datetime] = {}


def reset() -> None:
    """Забыть, о чём уже сообщали. Нужно тестам."""
    _seen.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def where_in_code(error: BaseException) -> str:
    """Последнее место в нашем коде, а не в чужой библиотеке.

    Внутри трассировки последние кадры почти всегда чужие — aiogram,
    SQLAlchemy, сам Python. Место, куда идти чинить, — самый глубокий из
    наших, поэтому ищем именно его.
    """
    own = ""
    for frame in traceback.extract_tb(error.__traceback__):
        try:
            path = Path(frame.filename).resolve()
            relative = path.relative_to(ROOT)
        except (ValueError, OSError):
            continue
        if relative.parts and relative.parts[0] in {"venv", ".venv", "site-packages"}:
            continue
        own = f"{relative}:{frame.lineno} в {frame.name}"
    return own


def describe(error: BaseException) -> str:
    """Одна строка про саму ошибку: тип и текст, без трассировки."""
    text = str(error).strip().replace("\n", " ")
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def signature(error: BaseException) -> str:
    """Чем одна поломка отличается от другой: тип плюс место в коде."""
    return f"{type(error).__name__}@{where_in_code(error) or 'неизвестно'}"


def _fresh(key: str) -> bool:
    """Не сообщали ли мы про это только что."""
    moment = _now()
    last = _seen.get(key)
    if last is not None and moment - last < COOLDOWN:
        return False
    if len(_seen) >= MAX_KINDS:
        # Выкидываем самое старое: словарь не должен расти без конца.
        oldest = min(_seen, key=_seen.get)
        _seen.pop(oldest, None)
    _seen[key] = moment
    return True


def render(error: BaseException, *, where: str, user_id: int | None = None) -> str:
    """Сообщение владельцу. Понятное человеку и достаточное для починки."""
    lines = ["🐞 Что-то сломалось в боте", "", f"Где: {where}"]
    if user_id is not None:
        lines.append(f"У кого: {user_id}")
    lines.append(f"Что: {describe(error)}")
    place = where_in_code(error)
    if place:
        lines.append(f"Строка: {place}")
    lines += ["", "Человеку я ответил, что поломка на нашей стороне и записи целы.",
              "Про эту же поломку следующие полчаса промолчу."]
    return "\n".join(lines)


async def report(bot: Bot | None, error: BaseException, *, where: str,
                 user_id: int | None = None) -> bool:
    """Записать поломку в лог и сообщить владельцу. Никогда не падает сам."""
    logger.exception("Поломка (%s): %s", where, describe(error),
                     exc_info=(type(error), error, error.__traceback__))
    return await _deliver(bot, signature(error),
                          render(error, where=where, user_id=user_id))


# Сколько символов берём из сообщения браузера. Текст приходит с телефона
# человека, поэтому обрезаем жёстко: в чат владельцу должна попасть строка
# ошибки, а не что угодно длиной с экран.
MAX_CLIENT_TEXT = 200


async def report_client(bot: Bot | None, message: str, *, where: str,
                        place: str = "", user_id: int | None = None) -> bool:
    """Поломка в приложении на телефоне: у нас там нет ни трассировки, ни кода.

    Такая ошибка страшнее серверной: человек видит пустой или застывший
    экран, а на сервере при этом всё в порядке и в логах чисто.
    """
    text = " ".join(str(message).split())[:MAX_CLIENT_TEXT]
    if not text:
        return False
    place = " ".join(str(place).split())[:MAX_CLIENT_TEXT]
    logger.warning("Поломка в приложении у %s (%s): %s | %s",
                   user_id, where, text, place)

    lines = ["🐞 Приложение сломалось на телефоне", "", f"Где: {where}"]
    if user_id is not None:
        lines.append(f"У кого: {user_id}")
    lines.append(f"Что: {text}")
    if place:
        lines.append(f"Строка: {place}")
    lines += ["", "Человек в это время видел пустой или застывший экран.",
              "Про эту же поломку следующие полчаса промолчу."]

    return await _deliver(bot, f"клиент@{place or text}", "\n".join(lines))


async def _deliver(bot: Bot | None, key: str, text: str) -> bool:
    """Отправить владельцу — с оглядкой на повторы и на часовой лимит."""
    if bot is None or not config.ADMIN_IDS:
        return False
    if not _fresh(key):
        return False

    try:
        return await alerts.send(bot, text)
    except Exception:  # noqa: BLE001 — сообщение о поломке не должно ломать ответ
        logger.warning("Не удалось сообщить владельцу о поломке", exc_info=True)
        return False


__all__ = ["COOLDOWN", "MAX_CLIENT_TEXT", "describe", "render", "report",
           "report_client", "reset", "signature", "where_in_code"]
