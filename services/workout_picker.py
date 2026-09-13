"""Подобрать занятие под то, что есть у человека прямо сейчас.

Каталог тренировок в приложении богатый, и в этом же его беда: тринадцать
программ, четыре направления, семь форм занятий. Человек, у которого есть
десять минут и мало сил, до занятия не доходит — он выбирает.

Здесь он не выбирает. Отвечает на два вопроса — сколько времени и как силы —
и получает одно занятие из той же базы. Нового каталога не заводим: берём то,
что уже есть, и решаем, что из него подходит.
"""

from __future__ import annotations

from dataclasses import dataclass

from seed.workout_programs import PROGRAMS
from utils.met import strength_exercise_minutes, timed_exercise_minutes

# Сколько минут занимает программа целиком — считается по её же упражнениям.
# Кэшируем: состав не меняется во время работы.
_minutes: dict[str, float] = {}

# Направления, которые коротки по своей природе: их можно делать где угодно
# и они не требуют ни переодеваться, ни отдыхать между подходами.
QUICK_CATEGORIES = ("posture", "eyes", "face")

# «Мало сил» — не повод не двигаться, но повод не поднимать тяжёлое.
CALM_STYLES = ("stretching", "yoga", "pilates")


@dataclass(frozen=True)
class Pick:
    """Что предложить и почему именно это."""

    code: str
    title: str
    subtitle: str
    category: str
    style: str | None
    location: str
    minutes: int
    exercises: int
    why: str

    def to_dict(self) -> dict:
        return {"code": self.code, "title": self.title, "subtitle": self.subtitle,
                "category": self.category, "style": self.style,
                "location": self.location, "minutes": self.minutes,
                "exercises": self.exercises, "why": self.why}


def program_minutes(code: str) -> float:
    """Сколько примерно займёт программа целиком."""
    if code in _minutes:
        return _minutes[code]

    total = 0.0
    for item in PROGRAMS[code]["exercises"]:
        # У упражнения «на время» (планка) есть седьмое поле — секунды на
        # подход. У обычного его нет, и считается оно по повторам.
        _, _, sets, reps, rest = item[0], item[1], item[2], item[3], item[4]
        seconds = item[6] if len(item) > 6 else None
        if seconds:
            total += timed_exercise_minutes(sets=sets, seconds_per_set=seconds,
                                            rest_seconds=rest)
        else:
            total += strength_exercise_minutes(sets=sets, reps=reps, rest_seconds=rest)
    _minutes[code] = round(total, 1)
    return _minutes[code]


def _why(program: dict, minutes: float, *, energy: int | None, available: int) -> str:
    """Одна фраза о том, почему предложено именно это."""
    if program["category"] in QUICK_CATEGORIES:
        return f"Коротко и без переодевания — примерно {round(minutes)} мин."
    if energy is not None and energy <= 2:
        return "Сил сегодня немного, поэтому спокойное занятие."
    if minutes <= available * 0.6:
        return f"Уложишься примерно в {round(minutes)} мин. — время ещё останется."
    return f"Примерно {round(minutes)} мин. — как раз под твоё время."


def pick(*, minutes_available: int = 30, energy: int | None = None,
         location: str | None = None, recent: tuple[str, ...] = (),
         category: str | None = None, limit: int = 3) -> list[Pick]:
    """Занятия, подходящие под время, силы и место. Первое — самое подходящее."""
    tired = energy is not None and energy <= 2

    scored: list[tuple[float, Pick]] = []
    for code, program in PROGRAMS.items():
        if category and program["category"] != category:
            continue
        if location and program["location"] != location:
            continue

        length = program_minutes(code)
        # Не влезает во время — не предлагаем: обещание, которого не сдержать.
        if length > minutes_available * 1.15:
            continue

        # Чем ближе к доступному времени, тем лучше: пятиминутка вместо
        # часа — это не «подобрал», а «отмахнулся».
        penalty = abs(minutes_available - length) / max(minutes_available, 1)
        if tired:
            calm = program.get("style") in CALM_STYLES
            quick = program["category"] in QUICK_CATEGORIES
            penalty -= 0.5 if (calm or quick) else -0.4
        if code in recent:
            # То же самое, что вчера, — не находка.
            penalty += 0.6

        scored.append((penalty, Pick(
            code=code, title=program["title"], subtitle=program["subtitle"],
            category=program["category"], style=program.get("style"),
            location=program["location"], minutes=round(length),
            exercises=len(program["exercises"]),
            why=_why(program, length, energy=energy, available=minutes_available),
        )))

    scored.sort(key=lambda pair: pair[0])
    return [item for _, item in scored[:limit]]


# Сколько минут считается «пятью минутами». Чуть с запасом: человек, который
# сказал «пять», не будет обижен шестью, но десять — это уже обман.
QUICK_LIMIT_MIN = 6.0
QUICK_TITLES = {
    "posture": "Осанка за пять минут",
    "eyes": "Глаза за пять минут",
    "face": "Лицо за пять минут",
    "body": "Размяться за пять минут",
}


@dataclass(frozen=True)
class QuickSet:
    """Короткий набор упражнений — не программа целиком, а её начало."""

    code: str
    title: str
    exercises: tuple[str, ...]
    minutes: int
    why: str

    def to_dict(self) -> dict:
        return {"code": self.code, "title": self.title, "minutes": self.minutes,
                "exercises": list(self.exercises), "why": self.why}


def _exercise_minutes(item) -> float:
    sets, reps, rest = item[2], item[3], item[4]
    seconds = item[6] if len(item) > 6 else None
    if seconds:
        return timed_exercise_minutes(sets=sets, seconds_per_set=seconds,
                                      rest_seconds=rest)
    return strength_exercise_minutes(sets=sets, reps=reps, rest_seconds=rest)


def quick_five(*, energy: int | None = None,
               recent: tuple[str, ...] = ()) -> list[QuickSet]:
    """«У меня пять минут» — короткие наборы из тех же упражнений.

    Целой программы на пять минут в базе нет, и придумывать её не нужно:
    берём начало подходящей программы и останавливаемся, когда время вышло.
    Это честнее, чем предложить пятнадцатиминутное занятие тому, у кого их
    пять.
    """
    out: list[QuickSet] = []
    order = list(QUICK_CATEGORIES) + ["body"]

    for category in order:
        best = None
        for code, program in PROGRAMS.items():
            if program["category"] != category or code in recent:
                continue
            # Для тела берём самое спокойное: за пять минут тяжёлое не делают.
            if category == "body" and program.get("style") not in CALM_STYLES:
                continue
            if best is None or program_minutes(code) < program_minutes(best):
                best = code
        if best is None:
            continue

        chosen: list[str] = []
        spent = 0.0
        for item in PROGRAMS[best]["exercises"]:
            length = _exercise_minutes(item)
            if spent + length > QUICK_LIMIT_MIN and chosen:
                break
            chosen.append(item[0])
            spent += length

        if len(chosen) < 2:
            continue
        out.append(QuickSet(
            code=best,
            title=QUICK_TITLES.get(category, PROGRAMS[best]["title"]),
            exercises=tuple(chosen),
            minutes=max(round(spent), 1),
            why=f"{len(chosen)} упражнения из «{PROGRAMS[best]['title']}» — "
                "остальное можно доделать потом",
        ))
    return out


__all__ = ["CALM_STYLES", "QUICK_CATEGORIES", "QUICK_LIMIT_MIN", "Pick",
           "QuickSet", "pick", "program_minutes", "quick_five"]
