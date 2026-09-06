"""Что сейчас происходит у человека — и что ему сейчас полезнее всего сделать.

Приложение до сих пор показывало цифры и предлагало разобраться самому:
«клетчатка 7 из 25» — и всё. Здесь оно начинает отвечать на следующий
вопрос: и что теперь?

Два правила, из которых всё остальное следует.

Первое: одно действие за раз. Показать человеку сразу пять недоборов —
значит не показать ни одного: он закроет приложение. Поэтому считается
несколько кандидатов, а наружу выходит один, самый уместный прямо сейчас.

Второе: работать на том, что есть. Ни одно поле не обязательно. Нет
чек-ина — не учитываем состояние; нет нормы клетчатки — не предлагаем её
добирать. Отсутствие данных не должно превращаться в «заполни профиль».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from utils.timeframe import get_zone

# Ночью не трогаем: полезнее спать, чем добирать клетчатку.
QUIET_FROM, QUIET_TO = 23, 7

# Насколько недобор считается заметным, чтобы о нём вообще говорить.
NOTABLE_GAP = 0.25

# Сколько раз за день можно предложить одно и то же. Повторённое трижды
# предложение перестают читать — и заодно перестают читать все остальные.
MAX_REPEATS = 2


@dataclass(frozen=True)
class DayContext:
    """Срез дня. Любое поле может быть неизвестно."""

    hour: int
    calories: float = 0.0
    calories_target: float | None = None
    protein_g: float = 0.0
    protein_target: float | None = None
    fiber_g: float = 0.0
    fiber_target: float | None = None
    water_ml: float = 0.0
    water_target: float | None = None
    meals_logged: int = 0
    steps: int = 0
    steps_goal: int | None = None
    steps_logged: bool = False
    workouts_today: int = 0
    days_since_measure: int | None = None
    energy: int | None = None
    stress: str | None = None
    checkin_done: bool = False
    streak: int = 0
    quests_left: int = 0
    preps_expiring: tuple[str, ...] = ()
    already_suggested: tuple[str, ...] = ()

    @property
    def quiet_hours(self) -> bool:
        return self.hour >= QUIET_FROM or self.hour < QUIET_TO

    @property
    def calories_left(self) -> float | None:
        if self.calories_target is None:
            return None
        return max(self.calories_target - self.calories, 0)

    def gap(self, name: str) -> float | None:
        """Какая доля нормы ещё не набрана: 0 — всё, 1 — ничего.

        None означает «не знаем»: нормы нет, и говорить не о чем.
        """
        value = getattr(self, name)
        target = getattr(self, f"{name.rsplit('_', 1)[0]}_target", None)
        if not target:
            return None
        return max(1 - value / target, 0.0)

    def seen(self, code: str) -> int:
        return self.already_suggested.count(code)


@dataclass(frozen=True)
class Action:
    """Одно предложение: что сделать и что нажать."""

    code: str
    title: str
    text: str
    cta: str
    target: str          # куда ведёт кнопка: water / cube / workout / checkin / meal
    score: float = 0.0
    amount: int = 0      # для воды — сколько добавить за одно нажатие

    def to_dict(self) -> dict:
        return {"code": self.code, "title": self.title, "text": self.text,
                "cta": self.cta, "target": self.target, "amount": self.amount}


def _candidates(ctx: DayContext) -> list[Action]:
    """Всё, что имело бы смысл предложить прямо сейчас."""
    out: list[Action] = []

    water_gap = ctx.gap("water_ml")
    if water_gap is not None and water_gap > 0.05 and 7 <= ctx.hour < 22:
        left = round((ctx.water_target or 0) - ctx.water_ml)
        text = ("Сегодня вода ещё не отмечена. Начнём с одного стакана?"
                if ctx.water_ml == 0 else
                f"До нормы воды осталось {left} мл. Стакан?")
        out.append(Action("water", "Вода", text, "+250 мл", "water",
                          score=water_gap * 1.1, amount=250))

    protein_gap = ctx.gap("protein_g")
    if protein_gap is not None and protein_gap > NOTABLE_GAP and ctx.hour >= 11:
        left = round((ctx.protein_target or 0) - ctx.protein_g)
        out.append(Action("protein", "Белок",
                          f"Белка сегодня {round(ctx.protein_g)} из "
                          f"{round(ctx.protein_target or 0)} г. Подберу что-нибудь "
                          f"с белком?",
                          "Подобрать еду", "cube", score=protein_gap))

    fiber_gap = ctx.gap("fiber_g")
    if fiber_gap is not None and fiber_gap > NOTABLE_GAP and ctx.hour >= 13:
        out.append(Action("fiber", "Клетчатка",
                          "До клетчатки сегодня далеко. Подберу что-нибудь простое?",
                          "Подобрать еду", "cube", score=fiber_gap * 0.9))

    if ctx.meals_logged == 0 and ctx.hour >= 10:
        out.append(Action("meal", "Еда",
                          "В дневнике сегодня пусто. Запишем хотя бы один приём?",
                          "Записать еду", "meal", score=1.2))
    elif ctx.calories_left and ctx.calories_left > 400 and ctx.hour >= 17:
        out.append(Action("meal", "Ужин",
                          f"На сегодня осталось ещё {round(ctx.calories_left)} ккал. "
                          "Подобрать ужин?",
                          "Подобрать еду", "cube", score=0.7))

    # Шаги приложение не считает само — их вносит человек. Поэтому сначала
    # напоминаем внести, и только потом говорим, сколько осталось пройти.
    if ctx.steps_goal and 9 <= ctx.hour < 22:
        if not ctx.steps_logged:
            out.append(Action("steps", "Шаги",
                              "Шаги за сегодня ещё не отмечены. Загляни в «Здоровье» "
                              "на телефоне и впиши число — это пара секунд.",
                              "Внести шаги", "steps", score=0.65))
        elif ctx.steps < ctx.steps_goal:
            left = ctx.steps_goal - ctx.steps
            minutes = max(round(left / 100), 1)
            out.append(Action("steps", "Шаги",
                              f"До цели осталось {left} шагов — это примерно "
                              f"{minutes} минут пешком.",
                              "Пройтись", "steps",
                              score=0.5 + 0.4 * (left / ctx.steps_goal)))

    # Тренировку не предлагаем на пустой батарейке: это не забота, а давление.
    if ctx.workouts_today == 0 and 9 <= ctx.hour < 21:
        tired = (ctx.energy is not None and ctx.energy <= 2) or ctx.stress == "high"
        if tired:
            out.append(Action("rest", "Движение",
                              "День выдался тяжёлый. Может, просто пройтись "
                              "десять минут?",
                              "Лёгкое движение", "workout", score=0.75))
        else:
            out.append(Action("movement", "Движение",
                              "Есть 10 минут? Можно закрыть задание движения.",
                              "Подобрать движение", "workout", score=0.6))

    if not ctx.checkin_done and 11 <= ctx.hour < 22:
        out.append(Action("checkin", "Состояние",
                          "Как ты сегодня? Одна отметка — и подсказки станут точнее.",
                          "Отметить", "checkin", score=0.5))

    if ctx.days_since_measure is not None and ctx.days_since_measure >= 7:
        out.append(Action("progress", "Замер",
                          f"Последний замер был {ctx.days_since_measure} дн. назад. "
                          "Взвесимся?",
                          "Записать замер", "progress", score=0.55))

    if ctx.preps_expiring:
        out.append(Action("prep", "Заготовки",
                          f"«{ctx.preps_expiring[0]}» лучше доесть сегодня.",
                          "Подобрать еду", "cube", score=0.8))

    return out


def next_action(ctx: DayContext) -> Action | None:
    """Одно самое уместное действие — или ничего, если всё в порядке."""
    if ctx.quiet_hours:
        return None

    ranked = []
    for action in _candidates(ctx):
        seen = ctx.seen(action.code)
        if seen >= MAX_REPEATS:
            continue
        # Пока совет висит на экране первый раз, он не штрафуется: человек
        # мог его ещё не прочитать, а прыгающая карточка сбивает с толку.
        # Штраф начинается со второго показа — то есть когда совет уже
        # уступал место другому и вернулся.
        ranked.append((action.score - max(seen - 1, 0) * 0.5, action))

    if not ranked:
        return None
    ranked.sort(key=lambda pair: -pair[0])
    best_score, best = ranked[0]
    return Action(best.code, best.title, best.text, best.cta, best.target,
                  score=round(best_score, 3), amount=best.amount)


def main_quest_codes(ctx: DayContext, quests: list[dict], limit: int = 3) -> list[str]:
    """Какие задания показать главными.

    Не первые три из списка, а те, что сегодня ближе к делу: невыполненные,
    начатые и совпадающие с тем, что и так предлагается сделать.
    """
    suggestion = next_action(ctx)
    preferred = {suggestion.code} if suggestion else set()
    # Задание про воду закрывается тем же действием, что и совет про воду.
    preferred |= {"water"} if "water" in preferred else set()

    def weight(quest: dict) -> tuple:
        return (
            quest.get("done", False),          # выполненные уходят вниз
            quest["code"] not in preferred,    # то, что советуем, — выше
            -quest.get("share", 0),            # начатое ближе к концу — выше
        )

    return [q["code"] for q in sorted(quests, key=weight)[:limit]]


def hour_in(timezone_name: str | None, *, now: datetime | None = None) -> int:
    zone = get_zone(timezone_name)
    return (now.astimezone(zone) if now else datetime.now(zone)).hour


__all__ = ["Action", "DayContext", "MAX_REPEATS", "NOTABLE_GAP", "hour_in",
           "main_quest_codes", "next_action"]
