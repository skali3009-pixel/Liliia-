"""Силуэт тела для экрана «Прогресс»: пропорции по замерам и ориентир по цели.

Фигура собирается из чисел, а не из картинки: ширина в каждой точке считается
по обхватам, поэтому силуэт меняется вместе с замерами — то, ради чего это и
затевалось. Здесь только арифметика, сама отрисовка — в webapp/static/app.js.

Всё измеряется в долях роста: рисунок тогда не зависит от размера экрана, а
высокая и низкая женщина с одинаковым обхватом талии выглядят по-разному —
как в жизни.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

# Обхват — это периметр, а не ширина. У почти круглого сечения ширина = C/π;
# торс в сечении ближе к овалу (шире, чем глубже), поэтому для талии, бёдер и
# груди берём поправку, а для рук и ног — нет.
TORSO_OVAL = 1.12
LIMB_OVAL = 1.0

# Плечи никто не мерит сантиметром, а без них фигуры нет: берём среднюю
# ширину плеч — примерно 0,108 роста. Занизишь — руки уедут внутрь силуэта
# и фигура станет бочкой без рук (проверено на рендере).
SHOULDER_RATIO = 0.108
NECK_RATIO = 0.024

# Пока замеров нет, показываем силуэт «примерно»: обхваты прикидываются по ИМТ.
# Правило грубое и намеренно простое — это заглушка до первого замера, о чём
# приложение честно пишет рядом с фигурой.
BASE_BMI = 22.0
ESTIMATE_RATIOS: dict[str, tuple[float, float]] = {
    # поле: (доля роста при ИМТ 22, прибавка за каждую единицу ИМТ)
    "bust": (0.500, 0.009),
    "waist": (0.400, 0.012),
    "hip": (0.550, 0.010),
    "thigh": (0.310, 0.006),
    "arm": (0.160, 0.004),
}

# Килограммы уходят неравномерно: сильнее всего меняется талия, слабее —
# руки и ноги. Числа — множители к общему изменению ширины, а не проценты.
GOAL_SENSITIVITY: dict[str, float] = {
    "bust": 1.0,
    "waist": 1.8,
    "hip": 1.0,
    "thigh": 0.8,
    "arm": 0.6,
}

# Ниже этого фигура-ориентир не сжимается: цель может быть выставлена
# как угодно, а рисовать нереалистичное тело нечестно.
GOAL_FLOOR = 0.78

# Здоровый диапазон веса считаем по ИМТ — это общепринятый ориентир,
# а не медицинская рекомендация.
HEALTHY_BMI_MIN = 18.5
HEALTHY_BMI_MAX = 24.9

MEASURE_TO_FIELD = {
    "bust": "chest_cm",
    "waist": "waist_cm",
    "hip": "hips_cm",
    "thigh": "thigh_cm",
    "arm": "arm_cm",
}


@dataclass(frozen=True)
class Silhouette:
    """Полуширины фигуры в долях её роста. Рисуются зеркально от оси."""

    shoulder: float
    bust: float
    waist: float
    hip: float
    thigh: float
    arm: float
    neck: float

    def to_dict(self) -> dict[str, float]:
        return {key: round(value, 5) for key, value in asdict(self).items()}


def half_width(circumference_cm: float, height_cm: float, *, oval: float = TORSO_OVAL) -> float:
    """Полуширина в долях роста по обхвату."""
    if circumference_cm <= 0 or height_cm <= 0:
        return 0.0
    width_cm = circumference_cm / math.pi * oval
    return width_cm / 2 / height_cm


def bmi(*, weight_kg: float, height_cm: float) -> float:
    if weight_kg <= 0 or height_cm <= 0:
        return 0.0
    return weight_kg / (height_cm / 100) ** 2


def healthy_weight_range(height_cm: float) -> tuple[int, int] | None:
    """Здоровый диапазон веса для роста — по ИМТ 18,5–24,9."""
    if height_cm <= 0:
        return None
    metres = height_cm / 100
    return round(HEALTHY_BMI_MIN * metres**2), round(HEALTHY_BMI_MAX * metres**2)


def estimated_circumferences(*, weight_kg: float, height_cm: float) -> dict[str, float]:
    """Прикидка обхватов по росту и весу — пока человек ничего не измерил."""
    index = bmi(weight_kg=weight_kg, height_cm=height_cm)
    if index <= 0:
        return {}
    return {
        key: max(base + step * (index - BASE_BMI), 0.05) * height_cm
        for key, (base, step) in ESTIMATE_RATIOS.items()
    }


def build_silhouette(
    *, measures: dict[str, float], height_cm: float, weight_kg: float
) -> tuple[Silhouette, bool]:
    """Силуэт по замерам. Чего нет — прикидывается по весу и росту.

    Второе значение — True, если хоть что-то пришлось прикинуть: тогда
    приложение подписывает фигуру как примерную.
    """
    guesses = estimated_circumferences(weight_kg=weight_kg, height_cm=height_cm)

    values: dict[str, float] = {}
    estimated = False
    for key in ("bust", "waist", "hip", "thigh", "arm"):
        measured = measures.get(key) or 0.0
        if measured > 0:
            values[key] = measured
        else:
            values[key] = guesses.get(key, 0.0)
            estimated = True

    limbs = {"thigh", "arm"}
    widths = {
        key: half_width(value, height_cm, oval=LIMB_OVAL if key in limbs else TORSO_OVAL)
        for key, value in values.items()
    }
    return (
        Silhouette(
            shoulder=SHOULDER_RATIO,
            neck=NECK_RATIO,
            **widths,
        ),
        estimated,
    )


def goal_silhouette(
    now: Silhouette, *, weight_kg: float, target_weight_kg: float
) -> Silhouette | None:
    """Фигура-ориентир для целевого веса.

    Вес меняется вместе с объёмом, а объём при неизменном росте — как квадрат
    ширины: отсюда корень. Дальше общее изменение раскладывается по зонам:
    талия отзывается сильнее, руки и ноги — слабее.
    """
    if weight_kg <= 0 or target_weight_kg <= 0 or target_weight_kg >= weight_kg:
        return None

    uniform = math.sqrt(target_weight_kg / weight_kg)
    shrink = 1 - uniform

    def scaled(key: str, value: float) -> float:
        factor = max(1 - shrink * GOAL_SENSITIVITY[key], GOAL_FLOOR)
        return value * factor

    return Silhouette(
        shoulder=now.shoulder,
        neck=now.neck,
        bust=scaled("bust", now.bust),
        waist=scaled("waist", now.waist),
        hip=scaled("hip", now.hip),
        thigh=scaled("thigh", now.thigh),
        arm=scaled("arm", now.arm),
    )


# Рисунок фигуры (webapp/static/img/body.webp) изображает женщину примерно
# такого телосложения. От него и считается, насколько растянуть картинку под
# настоящие замеры: сам рисунок остаётся тем же, меняются только пропорции.
# Нарисована женщина заметно полнее среднего — если считать её худой,
# все тела получаются «толстенькими», а разница между «сейчас» и «целью»
# почти не читается.
REFERENCE_BMI = 27.0

# Границы растяжения: цель можно выставить любую, а рисунок обязан остаться
# человеком. Диапазон широкий — иначе 59 и 90 кг выглядят одинаково.
WARP_MIN = 0.70
WARP_MAX = 1.42

WARP_ZONES = ("bust", "waist", "hip", "thigh", "arm")


def reference_silhouette(height_cm: float) -> Silhouette:
    """Фигура, которую изображает рисунок."""
    weight = REFERENCE_BMI * (height_cm / 100) ** 2 if height_cm > 0 else 0
    figure, _ = build_silhouette(measures={}, height_cm=height_cm, weight_kg=weight)
    return figure


def warp_factors(figure: Silhouette | None, *, height_cm: float) -> dict[str, float]:
    """Во сколько раз растянуть рисунок в каждой зоне под это тело."""
    if figure is None or height_cm <= 0:
        return {zone: 1.0 for zone in WARP_ZONES}

    reference = reference_silhouette(height_cm)
    factors = {}
    for zone in WARP_ZONES:
        base = getattr(reference, zone)
        value = getattr(figure, zone)
        ratio = value / base if base > 0 else 1.0
        factors[zone] = round(min(max(ratio, WARP_MIN), WARP_MAX), 4)
    return factors


@dataclass(frozen=True)
class Insight:
    """Строка с выводом под фигурой."""

    icon: str
    title: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _kg(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def build_insights(
    *,
    weight_kg: float | None,
    target_weight_kg: float | None,
    height_cm: float | None,
    waist_cm: float | None,
    protein_g: int | None,
    water_ml: int | None,
) -> list[Insight]:
    """Что сказать человеку рядом с фигурой.

    Ничего не диагностируем: это ориентиры и привычки, а не медицина —
    ровно так же, как написано в оферте.
    """
    insights: list[Insight] = []

    if weight_kg and target_weight_kg:
        left = weight_kg - target_weight_kg
        if left > 0.2:
            insights.append(Insight("⚖️", "До твоей цели", f"−{_kg(left)} кг"))
        elif left < -0.2:
            insights.append(Insight("⚖️", "До твоей цели", f"+{_kg(-left)} кг"))
        else:
            insights.append(Insight("⚖️", "Ты в цели", "держим вес"))

    if height_cm:
        healthy = healthy_weight_range(height_cm)
        if healthy:
            low, high = healthy
            insights.append(
                Insight("📐", "Здоровый диапазон", f"{low}–{high} кг для роста {round(height_cm)} см")
            )

    # Обхват талии меньше половины роста — общеизвестный бытовой ориентир.
    # Показываем его только когда талия измерена: пугать прикидкой нельзя.
    if waist_cm and height_cm:
        half = height_cm / 2
        if waist_cm > half:
            insights.append(
                Insight(
                    "〰️",
                    "Талия",
                    f"{round(waist_cm)} см при ориентире до {round(half)} см — "
                    "это зона, с которой стоит начать",
                )
            )
        else:
            insights.append(
                Insight("〰️", "Талия", f"{round(waist_cm)} см — в пределах ориентира")
            )

    if water_ml:
        insights.append(
            Insight(
                "💧",
                "Лимфа и отёки",
                f"Лимфа двигается только вместе с тобой: шаги, растяжка и "
                f"{water_ml / 1000:.1f} л воды в день".replace(".", ","),
            )
        )

    if protein_g:
        insights.append(
            Insight(
                "🏋️",
                "Мышцы",
                f"{protein_g} г белка в день и 2–3 силовые в неделю — "
                "тогда уходит жир, а не мышцы",
            )
        )

    return insights


def zones(measures: dict[str, float]) -> list[dict[str, Any]]:
    """Зоны на фигуре: что подсвечивать и чем подписывать.

    Порядок сверху вниз — как на теле, чтобы подписи не прыгали.
    """
    titles = [
        ("arm", "Руки", "arm"),
        ("bust", "Грудь", "chest"),
        ("waist", "Талия", "waist"),
        ("hip", "Бёдра", "hips"),
        ("thigh", "Бедро", "thigh"),
    ]
    return [
        {
            "code": code,
            # Метрика графика: по нажатию на зону экран показывает её динамику.
            "metric": metric,
            "label": label,
            "value": measures.get(code) or 0,
            "has_data": bool(measures.get(code)),
        }
        for code, label, metric in titles
    ]


__all__ = [
    "Insight",
    "Silhouette",
    "warp_factors",
    "reference_silhouette",
    "bmi",
    "build_insights",
    "build_silhouette",
    "estimated_circumferences",
    "goal_silhouette",
    "half_width",
    "healthy_weight_range",
    "zones",
]
