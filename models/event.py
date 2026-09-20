"""Маркетинговые события: сколько людей дошло докуда.

Заведено ради одного вопроса, на который в боте ответить было нечем: по
какой ссылке человек пришёл и дошёл ли он до пользы. Дневной отчёт
показывает, сколько всего людей и сколько дошло до конца анкеты, — но не
откуда они и что делали дальше.

**Хранится сводкой, а не потоком.** Одна строка на человека, событие, вид и
день; внутри счётчик. Ровно так уже устроен счёт нажатий кнопок
(`models/button.py`), и заводить рядом второй способ считать было бы двумя
системами учёта, которые разойдутся в первый же день. Поток событий здесь не
нужен: отчёт спрашивает «сколько людей» и «сколько раз», а не «во сколько
именно».

**Ничего личного внутри.** Ни веса, ни возраста, ни аллергий, ни фотографий,
ни переписки, ни ответов модели, ни платёжных данных. Только номер человека
(он и так есть в каждой таблице), короткий код события и день.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class MarketingEvent(Base):
    __tablename__ = "marketing_events"
    __table_args__ = (
        UniqueConstraint("user_id", "event", "kind", "day", name="uq_event_user_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True,
        nullable=False,
    )
    # Код события: bot_start, profile_completed, action_completed,
    # first_action_completed, active_day.
    event: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # Уточнение к событию: у запуска — новый профиль или уже существовавший,
    # у полезного действия — какого оно рода. Пусто там, где уточнять нечего.
    kind: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    day: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
