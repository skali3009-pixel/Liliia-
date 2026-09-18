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

# «Остался один шаг» — самый сильный повод из всех: маленькое усилие,
# понятная награда и одно действие. Поэтому у него отдельные пороги и
# отдельный вес, выше обычного недобора. Обычная подсказка тем весомее,
# чем больше не хватает; эта — наоборот, чем меньше.
ALMOST_SHARE = 0.2          # доля нормы, ниже которой недобор считается «чуть-чуть»
ALMOST_WATER_ML = 400       # но и в миллилитрах есть предел: пол-литра — не «чуть-чуть»
ALMOST_STEPS = 1500
ALMOST_CRYSTALS = 12

# Сколько раз за день можно предложить одно и то же. Повторённое трижды
# предложение перестают читать — и заодно перестают читать все остальные.
MAX_REPEATS = 2


def is_almost(left: float, target: float, cap: float) -> bool:
    """Осталось совсем немного: и по доле нормы, и по самой величине.

    Сработать должны оба порога, а не любой из них. Одной доли мало:
    двадцать процентов от полутора литров — триста миллилитров, это
    действительно «один стакан»; двадцать процентов от четырёх литров —
    восемьсот, и «остался шаг» тут уже враньё. Одной величины тоже мало:
    полтора километра до цели в тридцать тысяч шагов — не «чуть-чуть».
    """
    if not target:
        return False
    return 0 < left <= min(cap, target * ALMOST_SHARE)


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
    quests_total: int = 0
    # Сколько кристаллов до следующего уровня. Ноль — неизвестно.
    crystals_left: int = 0
    preps_expiring: tuple[str, ...] = ()
    already_suggested: tuple[str, ...] = ()
    # Номер дня. По нему выбирается вариант формулировки: в течение дня
    # текст не меняется (прыгающая карточка сбивает с толку), а назавтра
    # становится другим.
    day_seed: int = 0

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


# Одно и то же предложение, сказанное одними и теми же словами каждый день,
# перестают читать примерно на третий раз — а вместе с ним перестают читать
# и все остальные. Поэтому у каждого повода несколько формулировок. Смысл и
# действие в них одинаковые: разное здесь — слова, а не суть.
VARIANTS: dict[str, tuple[str, ...]] = {
    "water_empty": (
        "Сегодня вода ещё не отмечена. Начнём с одного стакана?",
        "Воды пока ни глотка. Стакан прямо сейчас?",
        "День идёт, а вода не отмечена. Начнём с малого?",
        "Про воду сегодня ещё ничего. Один стакан?",
        "Воды за сегодня нет. Начать можно со стакана.",
    ),
    "water_left": (
        "До нормы воды осталось {left} мл. Стакан?",
        "Ещё {left} мл — и вода на сегодня закрыта.",
        "Воды не хватает {left} мл. Это пара стаканов.",
        "{left} мл до нормы. Догоним?",
        "Осталось {left} мл воды. Начнём со стакана?",
    ),
    "water_almost": (
        "Ещё {left} мл — и вода на сегодня закрыта.",
        "Остался один стакан: {left} мл, и норма взята.",
        "До закрытой воды {left} мл. Совсем близко.",
        "{left} мл — и всё, вода сегодня сделана.",
        "Последние {left} мл. Закроем?",
    ),
    "steps_almost": (
        "До сегодняшней цели осталось {left} шагов — минут {minutes}.",
        "{left} шагов до цели. Одна короткая прогулка.",
        "Осталось {left} шагов, и день по движению закрыт.",
        "Ещё {left} шагов — это {minutes} минут пешком.",
        "Совсем близко: {left} шагов до цели.",
    ),
    "day_almost": (
        "Осталось одно небольшое действие, чтобы завершить день.",
        "Одно задание — и день закрыт полностью.",
        "До полного дня осталось одно дело.",
        "Остался один шаг до закрытого дня.",
        "Одно задание отделяет тебя от закрытого дня.",
    ),
    "level_almost": (
        "До следующего уровня осталось {left} кристаллов.",
        "Ещё {left} кристаллов — и уровень поднимется.",
        "{left} кристаллов до нового уровня.",
        "Новый уровень уже близко: {left} кристаллов.",
        "Осталось набрать {left} кристаллов до следующей ступени.",
    ),
    "protein": (
        "Белка сегодня {have} из {target} г. Подберу что-нибудь с белком?",
        "По белку пока {have} из {target} г. Собрать вариант?",
        "Белок сегодня отстаёт: {have} из {target} г. Подобрать еду?",
        "{have} из {target} г белка. Найти что-нибудь подходящее?",
        "До белка ещё далеко: {have} из {target} г. Подобрать?",
    ),
    "fiber": (
        "До клетчатки сегодня далеко. Подберу что-нибудь простое?",
        "Клетчатки сегодня маловато. Найти лёгкий вариант?",
        "По клетчатке день пока пустой. Подобрать что-нибудь?",
        "Овощей сегодня почти не было. Подберу вариант?",
        "Клетчатка отстаёт. Собрать что-то простое?",
    ),
    "meal_empty": (
        "В дневнике сегодня пусто. Запишем хотя бы один приём?",
        "За сегодня ни одной записи о еде. Начнём с любой?",
        "Дневник сегодня пока пустой. Одна запись — уже картина.",
        "Про еду сегодня ещё ничего. Запишем, что было?",
        "Ни одной записи о еде за день. Подойдёт любое фото.",
    ),
    "dinner": (
        "На сегодня осталось ещё {left} ккал. Подобрать ужин?",
        "До нормы ещё {left} ккал. Собрать ужин?",
        "Осталось {left} ккал — как раз на ужин. Подобрать?",
        "{left} ккал в запасе. Найти что-нибудь на вечер?",
        "На вечер есть ещё {left} ккал. Подберу ужин?",
    ),
    "steps_empty": (
        "Шаги за сегодня ещё не отмечены. Загляни в «Здоровье» на телефоне "
        "и впиши число — это пара секунд.",
        "Шаги сегодня не внесены. Число есть в «Здоровье» на телефоне.",
        "Про шаги сегодня ещё ничего. Впишешь число из «Здоровья»?",
        "Шаги пока не отмечены — их вношу не я, а ты. Пара секунд.",
        "Сегодняшние шаги ещё не записаны. Посмотри в «Здоровье».",
    ),
    "steps_left": (
        "До цели осталось {left} шагов — это примерно {minutes} минут пешком.",
        "Ещё {left} шагов до цели. Минут {minutes} прогулки.",
        "{left} шагов — и цель взята. Это {minutes} минут.",
        "Осталось пройти {left} шагов, примерно {minutes} минут.",
        "До нормы шагов {left}. Хватит {minutes} минут пешком.",
    ),
    "rest": (
        "День выдался тяжёлый. Может, просто пройтись десять минут?",
        "Сегодня непросто. Тренировку отложим — может, короткая прогулка?",
        "Сил немного. Десять минут неспешно — этого достаточно.",
        "Тяжёлый день. Никаких нагрузок, но пройтись можно.",
        "Батарейка на нуле. Пусть будет просто прогулка.",
    ),
    "movement": (
        "Есть 10 минут? Можно закрыть задание движения.",
        "Десять минут найдётся? Задание движения закроется.",
        "Короткое движение — 10 минут. Подобрать?",
        "Есть время на десять минут движения?",
        "Задание движения ещё открыто. Хватит десяти минут.",
    ),
    "checkin": (
        "Как ты сегодня? Одна отметка — и подсказки станут точнее.",
        "Отметишь самочувствие? Это меняет то, что я предлагаю.",
        "Как сегодня по силам? Одно нажатие.",
        "Расскажешь, как день? Подсказки станут ближе к делу.",
        "Одна отметка о самочувствии — и советы будут точнее.",
    ),
    "progress": (
        "Последний замер был {days} дн. назад. Взвесимся?",
        "Замера не было {days} дн. Запишем новый?",
        "Прошло {days} дн. с последнего замера. Пора?",
        "{days} дн. без замера — график скучает.",
        "Последняя цифра была {days} дн. назад. Обновим?",
    ),
    "prep": (
        "«{name}» лучше доесть сегодня.",
        "«{name}» стоит съесть сегодня — потом будет поздно.",
        "У «{name}» заканчивается срок. Сегодня в самый раз.",
        "«{name}» ждёт в холодильнике и долго не пролежит.",
        "Сегодня хороший день доесть «{name}».",
    ),
}


def say(seed: int, key: str, **values) -> str:
    """Одна из формулировок. В течение дня — всегда одна и та же."""
    options = VARIANTS[key]
    return options[seed % len(options)].format(**values)


def stamp(seed: int, key: str) -> str:
    """Подпись формулировки: набор и номер варианта. Ложится в историю,
    чтобы потом можно было сравнить, какие слова работают."""
    return f"{key}#{seed % len(VARIANTS[key])}"


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
    # Какой формулировкой сказано: имя набора и номер варианта. Без этого
    # нельзя потом узнать, какие слова работают, а какие нет: в истории
    # осталось бы «отправили про воду», а какими словами — неизвестно.
    wording: str = ""

    def to_dict(self) -> dict:
        return {"code": self.code, "title": self.title, "text": self.text,
                "cta": self.cta, "target": self.target, "amount": self.amount}


def _candidates(ctx: DayContext) -> list[Action]:
    """Всё, что имело бы смысл предложить прямо сейчас."""
    out: list[Action] = []

    water_gap = ctx.gap("water_ml")
    if water_gap is not None and water_gap > 0.05 and 7 <= ctx.hour < 22:
        left = round((ctx.water_target or 0) - ctx.water_ml)
        if is_almost(left, ctx.water_target or 0, ALMOST_WATER_ML):
            # Кнопка предлагает ровно столько, сколько осталось: «+250 мл»
            # там, где до нормы 300, — это ещё один заход завтра.
            step = max(50, min(500, int(round(left / 50.0)) * 50))
            out.append(Action("water", "Вода",
                              say(ctx.day_seed, "water_almost", left=left),
                              f"+{step} мл", "water", score=1.35, amount=step,
                              wording=stamp(ctx.day_seed, "water_almost")))
        else:
            key = "water_empty" if ctx.water_ml == 0 else "water_left"
            out.append(Action("water", "Вода", say(ctx.day_seed, key, left=left),
                              "+250 мл", "water", score=water_gap * 1.1, amount=250,
                              wording=stamp(ctx.day_seed, key)))

    protein_gap = ctx.gap("protein_g")
    if protein_gap is not None and protein_gap > NOTABLE_GAP and ctx.hour >= 11:
        left = round((ctx.protein_target or 0) - ctx.protein_g)
        out.append(Action("protein", "Белок",
                          say(ctx.day_seed, "protein", have=round(ctx.protein_g),
                              target=round(ctx.protein_target or 0)),
                          "Подобрать еду", "cube", score=protein_gap,
                          wording=stamp(ctx.day_seed, "protein")))

    fiber_gap = ctx.gap("fiber_g")
    if fiber_gap is not None and fiber_gap > NOTABLE_GAP and ctx.hour >= 13:
        out.append(Action("fiber", "Клетчатка", say(ctx.day_seed, "fiber"),
                          "Подобрать еду", "cube", score=fiber_gap * 0.9,
                          wording=stamp(ctx.day_seed, "fiber")))

    if ctx.meals_logged == 0 and ctx.hour >= 10:
        out.append(Action("meal", "Еда", say(ctx.day_seed, "meal_empty"),
                          "Записать еду", "meal", score=1.2,
                          wording=stamp(ctx.day_seed, "meal_empty")))
    elif ctx.calories_left and ctx.calories_left > 400 and ctx.hour >= 17:
        out.append(Action("meal", "Ужин",
                          say(ctx.day_seed, "dinner", left=round(ctx.calories_left)),
                          "Подобрать еду", "cube", score=0.7,
                          wording=stamp(ctx.day_seed, "dinner")))

    # Шаги приложение не считает само — их вносит человек. Поэтому сначала
    # напоминаем внести, и только потом говорим, сколько осталось пройти.
    if ctx.steps_goal and 9 <= ctx.hour < 22:
        if not ctx.steps_logged:
            out.append(Action("steps", "Шаги", say(ctx.day_seed, "steps_empty"),
                              "Внести шаги", "steps", score=0.65,
                              wording=stamp(ctx.day_seed, "steps_empty")))
        elif ctx.steps < ctx.steps_goal:
            left = ctx.steps_goal - ctx.steps
            minutes = max(round(left / 100), 1)
            close = is_almost(left, ctx.steps_goal, ALMOST_STEPS)
            key = "steps_almost" if close else "steps_left"
            out.append(Action("steps", "Шаги",
                              say(ctx.day_seed, key, left=left, minutes=minutes),
                              "Пройтись", "steps",
                              score=1.3 if close
                              else 0.5 + 0.4 * (left / ctx.steps_goal),
                              wording=stamp(ctx.day_seed, key)))

    # Тренировку не предлагаем на пустой батарейке: это не забота, а давление.
    if ctx.workouts_today == 0 and 9 <= ctx.hour < 21:
        tired = (ctx.energy is not None and ctx.energy <= 2) or ctx.stress == "high"
        if tired:
            out.append(Action("rest", "Движение", say(ctx.day_seed, "rest"),
                              "Лёгкое движение", "workout", score=0.75,
                              wording=stamp(ctx.day_seed, "rest")))
        else:
            # Самое слабое из всего, что мы предлагаем: это не вывод из
            # данных, а вежливый вопрос в пустоту. Шаги человек вносит
            # руками, и «ты мало двигалась» мы сказать не вправе. На экране
            # такой совет уместен, а звонить телефоном ради него — нет:
            # вес ниже порога, за которым бот пишет первым.
            out.append(Action("movement", "Движение", say(ctx.day_seed, "movement"),
                              "Подобрать движение", "workout", score=0.55,
                              wording=stamp(ctx.day_seed, "movement")))

    if not ctx.checkin_done and 11 <= ctx.hour < 22:
        out.append(Action("checkin", "Состояние", say(ctx.day_seed, "checkin"),
                          "Отметить", "checkin", score=0.5,
                          wording=stamp(ctx.day_seed, "checkin")))

    if ctx.days_since_measure is not None and ctx.days_since_measure >= 7:
        out.append(Action("progress", "Замер",
                          say(ctx.day_seed, "progress",
                              days=ctx.days_since_measure),
                          "Записать замер", "progress", score=0.55,
                          wording=stamp(ctx.day_seed, "progress")))

    # Закрытый день — понятная награда, и до него остаётся одно дело.
    if ctx.quests_total and ctx.quests_left == 1 and 9 <= ctx.hour < 22:
        out.append(Action("day", "День", say(ctx.day_seed, "day_almost"),
                          "Посмотреть день", "today", score=1.15,
                          wording=stamp(ctx.day_seed, "day_almost")))

    # Уровень — самый слабый из «остался шаг»: награда приятная, но не
    # сегодняшняя, и торопить с ней некрасиво.
    if 0 < ctx.crystals_left <= ALMOST_CRYSTALS and 10 <= ctx.hour < 22:
        out.append(Action("level", "Уровень",
                          say(ctx.day_seed, "level_almost", left=ctx.crystals_left),
                          "Посмотреть задания", "today", score=0.9,
                          wording=stamp(ctx.day_seed, "level_almost")))

    if ctx.preps_expiring:
        out.append(Action("prep", "Заготовки",
                          say(ctx.day_seed, "prep", name=ctx.preps_expiring[0]),
                          "Подобрать еду", "cube", score=0.8,
                          wording=stamp(ctx.day_seed, "prep")))

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
                  score=round(best_score, 3), amount=best.amount,
                  wording=best.wording)


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


__all__ = ["Action", "ALMOST_CRYSTALS", "ALMOST_SHARE", "ALMOST_STEPS",
           "ALMOST_WATER_ML", "DayContext", "MAX_REPEATS", "NOTABLE_GAP",
           "VARIANTS", "hour_in", "is_almost", "main_quest_codes",
           "next_action", "say", "stamp"]
