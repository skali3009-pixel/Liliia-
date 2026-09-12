"""Женский календарь: какой сегодня день цикла и что это значит.

Зачем он в приложении про еду и вес. Не ради самого календаря — таких
приложений и без нас достаточно. Ради одной вещи, которую больше некому
сказать: **вес перед месячными выше не потому, что человек что-то сделал
не так.** Женщина встаёт на весы, видит плюс полтора килограмма после
недели без единого нарушения и делает вывод, что всё зря. Это самая
частая причина бросить.

Приложение, которое знает и вес, и день цикла, может объяснить это в тот
самый момент, когда человек смотрит на график. Ни календарь без веса, ни
вес без календаря так не умеют.

Чего здесь нет и не будет:
- предсказаний как обещаний: цикл сдвигается от болезни, поездки, стресса,
  и «должны начаться завтра» — это оценка, а не расписание;
- медицинских выводов: никаких «у тебя нерегулярный цикл» и тем более
  причин. Мы считаем дни, а не ставим диагнозы;
- расчёта «безопасных дней». Это не средство контрацепции, и говорить об
  этом надо прямо, а не мелким шрифтом.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import CycleLog

# Обычная длина цикла. Берётся, только пока своих данных нет.
DEFAULT_LENGTH = 28

# Правдоподобные границы. Всё, что вне их, в среднее не берём: это почти
# всегда пропущенная отметка, а не такой цикл.
MIN_LENGTH, MAX_LENGTH = 18, 45

# Сколько последних циклов учитываем в среднем. Год назад человек мог жить
# совсем иначе.
RECENT = 6

# Предсказание появляется, только когда есть на чём его строить.
NEED_FOR_FORECAST = 2

# Сколько дней в среднем идут месячные, пока человек не отметил конец.
ASSUMED_PERIOD_DAYS = 5


@dataclass(frozen=True)
class Phase:
    """Отрезок цикла — простыми словами, без медицинских терминов."""

    code: str
    title: str
    note: str


PHASES = {
    "period": Phase("period", "Идут месячные",
                    "Сил обычно меньше. Это нормально и это пройдёт."),
    "after": Phase("after", "После месячных",
                   "Обычно самые бодрые дни цикла."),
    "middle": Phase("middle", "Середина цикла",
                    "Чаще всего сил больше всего именно сейчас."),
    "before": Phase("before", "Перед месячными",
                    "Может тянуть на сладкое, а вес — показывать больше "
                    "обычного из-за воды."),
}

# Это должно быть видно, а не спрятано мелким шрифтом.
DISCLAIMER = ("Календарь просто считает дни. Это не средство контрацепции "
              "и не медицинский вывод.")


@dataclass(frozen=True)
class State:
    """Что известно про цикл на сегодня."""

    day: int | None                 # какой сегодня день цикла, с единицы
    phase: Phase | None
    average_length: int | None      # своё среднее, если оно есть
    next_start: date | None         # оценка, а не обещание
    today: date
    starts: tuple[date, ...] = ()   # отмеченные начала, свежие первыми

    @property
    def known(self) -> bool:
        return self.day is not None

    @property
    def days_to_next(self) -> int | None:
        if self.next_start is None:
            return None
        return max((self.next_start - self.today).days, 0)

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase.code if self.phase else None,
            "title": self.phase.title if self.phase else None,
            "note": self.phase.note if self.phase else None,
            "average_length": self.average_length,
            "next_start": self.next_start.isoformat() if self.next_start else None,
            "days_to_next": self.days_to_next,
            "starts": [day.isoformat() for day in self.starts],
            "disclaimer": DISCLAIMER,
        }


def lengths(starts: list[date]) -> list[int]:
    """Длины циклов между соседними отметками — только правдоподобные.

    Пропущенная отметка даёт «цикл» в 56 дней. Взяв его в среднее, мы
    сдвинули бы все оценки и сделали бы календарь бесполезным именно там,
    где человек и так сбился.
    """
    ordered = sorted(starts)
    out = []
    for earlier, later in zip(ordered, ordered[1:]):
        span = (later - earlier).days
        if MIN_LENGTH <= span <= MAX_LENGTH:
            out.append(span)
    return out


def average_length(starts: list[date]) -> int | None:
    """Своя средняя длина цикла. None — пока считать не из чего."""
    recent = lengths(starts)[-RECENT:]
    if not recent:
        return None
    return round(sum(recent) / len(recent))


def phase_for(day: int, length: int, *, period_days: int = ASSUMED_PERIOD_DAYS) -> Phase:
    """Отрезок цикла по его дню. Границы приблизительные — как и всё здесь."""
    if day <= period_days:
        return PHASES["period"]
    # Последняя треть — «перед месячными»: именно там вес показывает воду.
    if day > length - 7:
        return PHASES["before"]
    if day <= length // 2:
        return PHASES["after"]
    return PHASES["middle"]


def build(starts: list[date], today: date) -> State:
    """Собрать состояние на сегодня из отмеченных начал."""
    past = sorted((day for day in starts if day <= today), reverse=True)
    if not past:
        return State(day=None, phase=None, average_length=average_length(starts),
                     next_start=None, starts=tuple(sorted(starts, reverse=True)),
                     today=today)

    last = past[0]
    day = (today - last).days + 1
    own = average_length(starts)
    length = own or DEFAULT_LENGTH

    # Если с последней отметки прошло больше самого длинного правдоподобного
    # цикла, считать день бессмысленно: человек просто перестал отмечать.
    if day > MAX_LENGTH:
        return State(day=None, phase=None, average_length=own, next_start=None,
                     starts=tuple(sorted(starts, reverse=True)), today=today)

    forecast = None
    if len(lengths(starts)) >= NEED_FOR_FORECAST - 1 and len(past) >= NEED_FOR_FORECAST:
        forecast = last + timedelta(days=length)

    return State(day=day, phase=phase_for(day, length), average_length=own,
                 next_start=forecast, starts=tuple(sorted(starts, reverse=True)),
                 today=today)


# Насколько вес должен отличаться от обычного, чтобы об этом стоило
# говорить. Меньше — это шум весов и время суток.
NOTABLE_KG = 0.3


def weight_note(state: State, *, latest_kg: float | None,
                usual_kg: float | None) -> str | None:
    """Объяснить вес перед месячными — то, ради чего календарь и заведён.

    Женщина встаёт на весы после недели без единого нарушения, видит плюс
    полтора килограмма и делает вывод, что всё зря. Это самая частая
    причина бросить, и сказать об этом больше некому: календарь без веса
    не знает про вес, а весы без календаря — про день цикла.

    Осторожно с формулировками: «обычно», «чаще всего», а не «это вода».
    Мы не знаем, отчего именно вырос вес у конкретного человека.
    """
    if state.phase is None or latest_kg is None or usual_kg is None:
        return None
    if state.phase.code not in {"before", "period"}:
        return None

    difference = round(latest_kg - usual_kg, 1)
    if difference < NOTABLE_KG:
        return None

    # Запятая только в числе. Замена по всей строке однажды уже превратила
    # точку в конце предложения в запятую — см. utils/body.py.
    shown = f"{difference:.1f}".replace(".", ",")
    when = ("Перед месячными" if state.phase.code == "before"
            else "В эти дни")
    return (f"{when} вес часто бывает выше — тело задерживает воду. "
            f"Сейчас разница {shown} кг с обычным. Это не жир, и через "
            "несколько дней она уходит сама.")


# --- работа с базой -------------------------------------------------------


async def all_starts(session: AsyncSession, user_id: int) -> list[date]:
    return list((await session.execute(
        select(CycleLog.started_on).where(CycleLog.user_id == user_id)
        .order_by(CycleLog.started_on.desc())
    )).scalars().all())


async def state(session: AsyncSession, user_id: int, today: date) -> State:
    return build(await all_starts(session, user_id), today)


async def mark(session: AsyncSession, user_id: int, day: date) -> bool:
    """Отметить начало. Повторное нажатие на тот же день снимает отметку.

    Снимать обязательно: промахнуться по дате легко, а календарь, из
    которого нельзя убрать ошибку, начинает врать навсегда.
    """
    row = (await session.execute(
        select(CycleLog).where(CycleLog.user_id == user_id,
                               CycleLog.started_on == day)
    )).scalar_one_or_none()

    if row is not None:
        await session.delete(row)
        await session.commit()
        return False

    session.add(CycleLog(user_id=user_id, started_on=day))
    await session.commit()
    return True


__all__ = [
    "ASSUMED_PERIOD_DAYS", "DEFAULT_LENGTH", "DISCLAIMER", "MAX_LENGTH",
    "MIN_LENGTH", "NEED_FOR_FORECAST", "PHASES", "RECENT", "Phase", "State",
    "all_starts", "average_length", "build", "lengths", "mark", "phase_for",
    "state", "weight_note",
]
