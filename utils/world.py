"""Мир, который растёт от того, что человек и так делает.

Девять открытий в приложении были карточками достижений: получил — и она
легла в коллекцию. Здесь то же самое становится местом, которое меняется.
Зона не просто «открыта»: она проходит ступени, и человек видит, что мир
двигается, а не просто копятся значки.

Ничего нового отмечать не нужно. Все ступени считаются по тому, что уже
записывается: дни с дневником, дни с нормой воды, тренировки, замеры,
серия и уровень.

Названия зон взяты из списка, который дала владелица: сад, озеро, тропа,
обсерватория, арена, храм, кристальная зона, логово гепарда.
"""

from __future__ import annotations

from dataclasses import dataclass

from utils.plural import plural


@dataclass(frozen=True)
class Zone:
    """Место в мире и то, чем оно растёт."""

    code: str
    name: str
    icon: str
    story: str
    metric: str                     # какое число двигает зону
    # Слово при числе в трёх формах: «1 день», «2 дня», «5 дней». Без этого
    # приложение выдаёт «1 дней» и разговаривает как машина.
    unit: tuple[str, str, str]
    stages: tuple[str, ...]         # названия ступеней, от первой до последней
    thresholds: tuple[int, ...]     # при каком значении наступает каждая
    # Во сколько дней обычной жизни обходится одна единица. Нужен, чтобы
    # сравнивать несравнимое: «ещё один замер» и «ещё один уровень» — это
    # неделя и два дня, а по долям выглядят одинаково.
    pace: float = 1.0

    @property
    def opens_at(self) -> int:
        return self.thresholds[0]


# Порядок важен: так зоны показываются и в таком порядке открываются.
ZONES: tuple[Zone, ...] = (
    Zone("garden", "Сад", "🌱",
         "Начинается с одной записи и растёт вместе с дневником.",
         metric="diary_days", unit=("день с дневником", "дня с дневником",
                                    "дней с дневником"),
         stages=("Росток", "Грядка", "Сад", "Цветущий сад"),
         thresholds=(1, 7, 21, 60), pace=1.0),
    Zone("lake", "Озеро", "💧",
         "Наполняется каждый раз, когда норма воды закрыта.",
         metric="water_days", unit=("день с нормой воды", "дня с нормой воды",
                                    "дней с нормой воды"),
         stages=("Родник", "Ручей", "Пруд", "Озеро"),
         thresholds=(3, 10, 25, 60), pace=1.3),
    Zone("trail", "Тропа", "🥾",
         "Протаптывается тренировками — по одной за раз.",
         metric="workout_days", unit=("тренировка", "тренировки", "тренировок"),
         stages=("Первый след", "Тропинка", "Тропа", "Горный маршрут"),
         thresholds=(2, 6, 18, 45), pace=2.0),
    Zone("observatory", "Обсерватория", "🔭",
         "Открывается, когда появляется, за чем наблюдать: замеры.",
         metric="measurements", unit=("замер", "замера", "замеров"),
         stages=("Подзорная труба", "Площадка", "Купол", "Обсерватория"),
         thresholds=(2, 5, 12, 30), pace=7.0),
    Zone("arena", "Арена", "🏟",
         "Строится долгой привычкой возвращаться.",
         metric="streak", unit=("день подряд", "дня подряд", "дней подряд"),
         stages=("Круг на песке", "Помост", "Трибуны", "Арена"),
         thresholds=(3, 7, 21, 60), pace=1.0),
    Zone("crystal", "Кристальная зона", "💎",
         "Растёт вместе с уровнем — из кристаллов.",
         metric="level", unit=("уровень", "уровня", "уровней"),
         stages=("Осколок", "Друза", "Жила", "Кристальный зал"),
         thresholds=(2, 5, 10, 20), pace=2.5),
    Zone("temple", "Храм", "🏛",
         "Появляется там, где тело меняется.",
         metric="weight_lost_kg", unit=("кг от старта", "кг от старта",
                                        "кг от старта"),
         stages=("Ступени", "Портик", "Зал", "Храм"),
         thresholds=(1, 3, 6, 12), pace=10.0),
    Zone("den", "Логово гепарда", "🐆",
         "Гепард обживается, когда мир становится своим.",
         metric="grown", unit=("ступень в мире", "ступени в мире",
                                   "ступеней в мире"),
         stages=("Следы", "Укрытие", "Логово", "Дом"),
         thresholds=(6, 12, 20, 28), pace=1.5),
)

ZONE_BY_CODE = {zone.code: zone for zone in ZONES}


@dataclass(frozen=True)
class ZoneState:
    """Как зона выглядит у конкретного человека прямо сейчас."""

    zone: Zone
    value: float
    stage: int              # 0 — ещё закрыта, дальше 1..len(stages)

    @property
    def open(self) -> bool:
        return self.stage > 0

    @property
    def title(self) -> str:
        return self.zone.stages[self.stage - 1] if self.open else self.zone.name

    @property
    def maxed(self) -> bool:
        return self.stage >= len(self.zone.stages)

    @property
    def next_at(self) -> int | None:
        """При каком значении наступит следующая ступень."""
        return None if self.maxed else self.zone.thresholds[self.stage]

    @property
    def left(self) -> float:
        target = self.next_at
        return 0.0 if target is None else max(target - self.value, 0)

    @property
    def share(self) -> float:
        """Насколько близко до следующей ступени, 0..1."""
        target = self.next_at
        if target is None:
            return 1.0
        previous = self.zone.thresholds[self.stage - 1] if self.open else 0
        span = max(target - previous, 1)
        return min(max((self.value - previous) / span, 0.0), 1.0)

    @property
    def days_left(self) -> float:
        """Сколько примерно дней обычной жизни до следующей ступени."""
        return self.left * self.zone.pace

    @property
    def hint(self) -> str:
        """Что сделать, чтобы это место сдвинулось."""
        if self.maxed:
            return "Выросло полностью"
        left = self.left
        word = plural(int(left), *self.zone.unit)
        if not self.open:
            return f"Откроется: ещё {_amount(left)} {word}"
        return f"До ступени «{self.zone.stages[self.stage]}»: ещё {_amount(left)} {word}"

    def to_dict(self) -> dict:
        return {"code": self.zone.code, "name": self.zone.name,
                "icon": self.zone.icon, "story": self.zone.story,
                "title": self.title, "stage": self.stage,
                "stages": len(self.zone.stages), "open": self.open,
                "maxed": self.maxed, "share": round(self.share, 3),
                "hint": self.hint}


def _amount(value: float) -> str:
    return f"{value:.0f}" if value == int(value) else f"{value:.1f}"


def stage_of(zone: Zone, value: float) -> int:
    """На какой ступени зона при таком значении."""
    stage = 0
    for threshold in zone.thresholds:
        if value >= threshold:
            stage += 1
    return stage


def build(facts: dict[str, float]) -> list[ZoneState]:
    """Состояние всех зон по числам, которые и так считаются.

    Логово гепарда зависит от остальных зон, поэтому считается последним:
    оно про мир целиком, а не про отдельную привычку.
    """
    states: list[ZoneState] = []
    for zone in ZONES:
        if zone.metric == "grown":
            continue
        value = float(facts.get(zone.metric, 0))
        states.append(ZoneState(zone, value, stage_of(zone, value)))

    den = ZONE_BY_CODE["den"]
    grown = sum(state.stage for state in states)
    states.append(ZoneState(den, grown, stage_of(den, grown)))

    # Возвращаем в объявленном порядке, а не в порядке подсчёта.
    order = {zone.code: index for index, zone in enumerate(ZONES)}
    states.sort(key=lambda state: order[state.zone.code])
    return states


def next_unlock(states: list[ZoneState]) -> ZoneState | None:
    """Ближайшее открытие: до чего меньше всего осталось.

    Считаем в днях обычной жизни, а не в долях. «Ещё один замер» и «ещё один
    уровень» по долям выглядят одинаково, а на деле это неделя и пара дней —
    и человек, которому показали недостижимое, просто перестанет смотреть.

    Сначала ещё не открытые места: появление нового заметнее, чем очередная
    ступень знакомого.
    """
    closed = [s for s in states if not s.open]
    growing = [s for s in states if s.open and not s.maxed]
    pool = closed or growing
    if not pool:
        return None
    return min(pool, key=lambda state: state.days_left)


def headline(states: list[ZoneState]) -> tuple[str, str]:
    """Заголовок мира: чем он сейчас является.

    Ни при каких обстоятельствах не упрёк: мир не отбирают за пропуски,
    он просто ждёт.
    """
    opened = [s for s in states if s.open]
    if not opened:
        return "Пустая долина", "Здесь пока тихо. Первая запись — и появится росток."
    if len(opened) == len(states):
        return "Полный мир", "Открыто всё. Дальше места растут вглубь."
    grown = sum(s.stage for s in opened)
    if grown >= len(states) * 2:
        return "Обжитый край", f"Мест открыто: {len(opened)}. Они уже подросли."
    return "Твой мир", f"Мест открыто: {len(opened)} из {len(states)}."


__all__ = ["ZONES", "ZONE_BY_CODE", "Zone", "ZoneState", "build", "headline",
           "next_unlock", "stage_of"]
