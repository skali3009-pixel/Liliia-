"""Как человек виден в общей таблице шагов «Неделя приложения».

Раньше таблица показывала всем настоящее имя из Telegram — любому, кто
открыл приложение, без спроса у самого человека (увидено на записи экрана
26.09). Теперь по умолчанию — псевдоним, имя — только если человек сам
выбрал его показывать, и из таблицы можно выйти, ничего не теряя: дневник
шагов, команда и друзья остаются.

Своя таблица, а не колонки в `users`: её создаёт `create_all()` при запуске,
существующие таблицы не трогаются, и откат на прежнюю версию кода ничего
не ломает — прежний код про неё просто не знает. Нет строки — значит, всё
по умолчанию: псевдоним и участие.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class BoardPrefs(Base):
    __tablename__ = "board_prefs"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Показывать настоящее имя вместо псевдонима. Только по выбору человека.
    show_name: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Не участвовать в общей таблице вовсе.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
