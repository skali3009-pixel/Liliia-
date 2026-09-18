"""Письмо тому, кто начал анкету и не дошёл до конца.

Дыра здесь была полная и тихая. И напоминания, и письма вернувшимся отбирают
людей по `onboarding_completed = True` — то есть человек, бросивший анкету на
четвёртом вопросе, не получал от бота больше ничего и никогда. Он не «ушёл»,
он застрял в дверях: согласился с условиями, начал отвечать, отвлёкся — и на
этом всё закончилось навсегда.

Правила у письма жёсткие, и они важнее текста.

- **Одно письмо, а не два.** Тот, кто бросил анкету, не «пропал» — он ещё
  ничем не пользовался, и напоминать ему о недоделанном деле второй раз
  значит выпрашивать. Письмам вернувшимся положено два, потому что там за
  спиной месяцы работы; здесь за спиной нет ничего.
- **На следующий день, а не через час.** Через час человек ещё занят тем,
  на что отвлёкся. Через неделю он уже забыл, что вообще ставил бота.
- **Только тем, кто согласился с условиями.** Не согласился — значит, мы не
  вправе ему писать вовсе, и никакая польза этого не отменяет.
- **Ни одного упрёка и ни одной цифры про тело.** Человек ничего нам не
  обещал.
- **Говорим, сколько осталось, а не сколько он не сделал.** «Осталось четыре
  вопроса» — это про конец пути, «ты ответил на пять из девяти» — про долг.

Состояние нигде не хранится: письмо уходит ровно на следующий день в полдень
по местному времени. Ответил на вопрос — счёт начинается заново, и письмо
просто не наступит.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from utils.timeframe import DEFAULT_TIMEZONE, matching_zones, to_local, today_in

logger = logging.getLogger(__name__)

# Ровно на следующий день после того, как человек замолчал.
AWAY_DAYS = 1

# Полдень: утро занято сборами, вечер — усталостью, а днём письмо просто
# лежит в чате и ждёт. Час тот же, что у писем вернувшимся, — двух разных
# представлений о «удобном времени» в проекте быть не должно.
SEND_AT = time(12, 0)


@dataclass(frozen=True)
class Letter:
    """Кому пишем, на каком он вопросе и что именно уходит."""

    user_id: int
    step: int          # номер вопроса, на котором остановился; 0 — неизвестно
    total: int
    text: str


def render(step: int, total: int) -> str:
    """Текст письма. Про остаток пути, а не про недоделанное."""
    if step:
        осталось = total - step + 1
        хвост = (f"Ты остановилась на вопросе {step} из {total}. "
                 f"Осталось {осталось} — это меньше минуты.")
    else:
        # Состояние не нашлось: строку могли убрать как несвежую. Врать про
        # номер нельзя, а звать всё равно надо.
        хвост = f"Анкета — {total} коротких вопросов, это минута."

    return (
        "🐆 Я досчитаю норму, как только ты ответишь.\n\n"
        f"{хвост}\n\n"
        "Без анкеты я не знаю твою норму калорий и воды — а без неё "
        "фотография еды покажет блюдо, но не скажет, много это для тебя "
        "или мало."
    )


async def _stopped_at(session: AsyncSession, user_ids: list[int]) -> dict[int, int]:
    """На каком вопросе стоит каждый — по сохранённому состоянию разговора.

    Читаем через тот же список шагов, которым пользуется сама анкета: второй
    таблицы «какой вопрос какой по счёту» в проекте быть не должно — она
    разошлась бы с анкетой в первый же день, когда вопрос добавят.
    """
    from handlers.onboarding import ПО_СОСТОЯНИЮ, номер_шага
    from models import FsmState

    rows = (await session.execute(
        select(FsmState.key, FsmState.state).where(FsmState.state.is_not(None))
    )).all()

    нужны = set(user_ids)
    где: dict[int, int] = {}
    for key, state in rows:
        шаг = ПО_СОСТОЯНИЮ.get(state)
        if шаг is None:
            continue
        части = key.split(":")
        if len(части) < 3:
            continue
        try:
            uid = int(части[2])
        except ValueError:
            continue
        if uid in нужны:
            где[uid] = номер_шага(шаг)
    return где


async def due(session: AsyncSession, *, now_utc: datetime | None = None) -> list[Letter]:
    """Кому сейчас, по их местному времени, пора написать про анкету."""
    from handlers.onboarding import ВСЕГО_ШАГОВ

    moment = now_utc or datetime.now(timezone.utc)

    zones = (await session.execute(
        select(User.timezone).where(
            User.onboarding_completed.is_(False),
            User.reminders_enabled.is_(True),
            User.legal_accepted_at.is_not(None),
        ).distinct()
    )).scalars().all()
    ready = matching_zones(moment, SEND_AT, zones)
    if not ready:
        return []

    users = (await session.execute(
        select(User).where(
            User.onboarding_completed.is_(False),
            User.reminders_enabled.is_(True),
            User.legal_accepted_at.is_not(None),
            User.timezone.in_(ready),
        )
    )).scalars().all()
    if not users:
        return []

    где = await _stopped_at(session, [user.id for user in users])

    letters: list[Letter] = []
    for user in users:
        zone = user.timezone or DEFAULT_TIMEZONE
        последний = user.last_bot_action or user.created_at
        if последний is None:
            continue
        молчит = (today_in(zone, now=moment) - to_local(последний, zone).date()).days
        if молчит != AWAY_DAYS:
            continue

        шаг = где.get(user.id, 0)
        letters.append(Letter(user_id=user.id, step=шаг, total=ВСЕГО_ШАГОВ,
                              text=render(шаг, ВСЕГО_ШАГОВ)))

    return letters


__all__ = ["AWAY_DAYS", "SEND_AT", "Letter", "due", "render"]
