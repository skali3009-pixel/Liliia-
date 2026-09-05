"""Тесты фигуры на экране «Прогресс»: пропорции, ориентир по цели, выводы."""

import pytest

from utils.body import (
    GOAL_FLOOR,
    build_insights,
    build_silhouette,
    estimated_circumferences,
    goal_silhouette,
    half_width,
    healthy_weight_range,
    zones,
)

# Женщина 165 см, 65 кг, замеры сняты полностью.
MEASURES = {"bust": 92, "waist": 78, "hip": 100, "thigh": 58, "arm": 28}
HEIGHT = 165
WEIGHT = 65


def silhouette(**kwargs):
    args = {"measures": MEASURES, "height_cm": HEIGHT, "weight_kg": WEIGHT, **kwargs}
    return build_silhouette(**args)


def test_wider_circumference_gives_wider_figure():
    narrow = half_width(70, HEIGHT)
    wide = half_width(90, HEIGHT)
    assert wide > narrow


def test_same_circumference_looks_wider_on_a_shorter_woman():
    """Ширина считается в долях роста — иначе высокая и низкая с одинаковой
    талией нарисовались бы одинаково."""
    assert half_width(80, 155) > half_width(80, 180)


def test_limbs_are_measured_as_round_and_torso_as_oval():
    """Бедро круглое в сечении, талия — овальная: у них разные поправки."""
    from utils.body import LIMB_OVAL, TORSO_OVAL

    assert TORSO_OVAL > LIMB_OVAL == 1.0
    assert half_width(80, HEIGHT, oval=TORSO_OVAL) > half_width(80, HEIGHT, oval=LIMB_OVAL)


def test_figure_keeps_anatomy_in_order():
    """Проверяем то, что видно глазом: бёдра шире талии, ноги не шире таза."""
    figure, estimated = silhouette()

    assert estimated is False
    assert figure.hip > figure.waist
    assert figure.bust > figure.waist
    # Две ноги рядом занимают примерно ширину таза, а не больше.
    assert figure.thigh * 2 <= figure.hip * 1.1


def test_missing_measurements_are_estimated_and_marked():
    figure, estimated = silhouette(measures={})

    assert estimated is True
    assert figure.waist > 0 and figure.hip > 0


def test_estimate_grows_with_weight():
    light = estimated_circumferences(weight_kg=55, height_cm=HEIGHT)
    heavy = estimated_circumferences(weight_kg=85, height_cm=HEIGHT)
    assert heavy["waist"] > light["waist"]


def test_one_measured_value_is_kept_and_the_rest_estimated():
    figure, estimated = silhouette(measures={"waist": 70})

    assert estimated is True
    assert figure.waist == pytest.approx(half_width(70, HEIGHT), rel=1e-6)


def test_goal_figure_is_narrower_but_keeps_the_skeleton():
    figure, _ = silhouette()
    goal = goal_silhouette(figure, weight_kg=WEIGHT, target_weight_kg=58)

    assert goal is not None
    assert goal.waist < figure.waist
    assert goal.hip < figure.hip
    # Плечи и шея — это кости, от похудения они не меняются.
    assert goal.shoulder == figure.shoulder
    assert goal.neck == figure.neck


def test_waist_reacts_to_weight_loss_stronger_than_arms():
    """Килограммы уходят неравномерно — иначе фигура-цель просто копия."""
    figure, _ = silhouette()
    goal = goal_silhouette(figure, weight_kg=WEIGHT, target_weight_kg=58)

    waist_change = 1 - goal.waist / figure.waist
    arm_change = 1 - goal.arm / figure.arm
    assert waist_change > arm_change > 0


def test_no_goal_figure_without_a_target():
    figure, _ = silhouette()
    assert goal_silhouette(figure, weight_kg=WEIGHT, target_weight_kg=0) is None


def test_goal_above_current_weight_draws_nothing():
    """Цель тяжелее нынешнего веса — рисовать «располневшую» фигуру не будем."""
    figure, _ = silhouette()
    assert goal_silhouette(figure, weight_kg=60, target_weight_kg=70) is None


def test_absurd_target_does_not_draw_an_impossible_body():
    figure, _ = silhouette()
    goal = goal_silhouette(figure, weight_kg=WEIGHT, target_weight_kg=25)

    assert goal.waist >= figure.waist * GOAL_FLOOR - 1e-9


def test_healthy_range_matches_the_bmi_table():
    low, high = healthy_weight_range(165)
    assert (low, high) == (50, 68)


def test_insight_says_how_much_is_left():
    lines = build_insights(
        weight_kg=65, target_weight_kg=58, height_cm=165,
        waist_cm=78, protein_g=124, water_ml=2170,
    )
    text = " ".join(f"{item.title} {item.text}" for item in lines)

    assert "−7 кг" in text
    assert "50–68 кг" in text
    # То, о чём просили: лимфа и мышцы — привычками, а не диагнозами.
    assert "Лимфа" in text and "белка" in text


def test_wide_waist_is_named_as_a_starting_point_not_a_diagnosis():
    lines = build_insights(
        weight_kg=95, target_weight_kg=70, height_cm=165,
        waist_cm=95, protein_g=100, water_ml=2000,
    )
    waist_line = next(item for item in lines if item.title == "Талия")

    assert "стоит начать" in waist_line.text
    assert "ориентире" in waist_line.text or "ориентир" in waist_line.text


def test_waist_line_is_silent_without_a_real_measurement():
    """Пугать человека прикидкой по весу нельзя — только измеренной талией."""
    lines = build_insights(
        weight_kg=95, target_weight_kg=70, height_cm=165,
        waist_cm=None, protein_g=100, water_ml=2000,
    )
    assert all(item.title != "Талия" for item in lines)


def test_empty_profile_gives_no_made_up_advice():
    assert build_insights(
        weight_kg=None, target_weight_kg=None, height_cm=None,
        waist_cm=None, protein_g=None, water_ml=None,
    ) == []


def test_zones_point_at_the_chart_metrics_that_exist():
    from services.progress import MEASURE_FIELDS

    for zone in zones(MEASURES):
        assert zone["metric"] in MEASURE_FIELDS
        assert zone["has_data"] is True


def test_zone_without_a_measurement_is_marked_empty():
    empty = {zone["code"]: zone for zone in zones({"waist": 70})}
    assert empty["waist"]["has_data"] is True
    assert empty["thigh"]["has_data"] is False


def test_warp_matches_the_drawing_for_a_reference_body():
    """Тело, которое и нарисовано, растягивать не нужно."""
    from utils.body import REFERENCE_BMI, reference_silhouette, warp_factors

    figure = reference_silhouette(165)
    factors = warp_factors(figure, height_cm=165)
    assert all(abs(value - 1.0) < 1e-6 for value in factors.values())
    assert REFERENCE_BMI > 0


def test_wider_body_stretches_the_drawing_and_slimmer_shrinks_it():
    from utils.body import warp_factors

    wide, _ = build_silhouette(measures={"waist": 95}, height_cm=165, weight_kg=85)
    narrow, _ = build_silhouette(measures={"waist": 62}, height_cm=165, weight_kg=52)

    assert warp_factors(wide, height_cm=165)["waist"] > 1
    assert warp_factors(narrow, height_cm=165)["waist"] < 1


def test_warp_never_turns_the_drawing_into_a_funhouse_mirror():
    """Цель можно выставить любую — рисунок обязан остаться человеком."""
    from utils.body import WARP_MAX, WARP_MIN, warp_factors

    huge, _ = build_silhouette(measures={"waist": 200}, height_cm=150, weight_kg=200)
    tiny, _ = build_silhouette(measures={"waist": 30}, height_cm=190, weight_kg=35)

    assert warp_factors(huge, height_cm=150)["waist"] == WARP_MAX
    assert warp_factors(tiny, height_cm=190)["waist"] == WARP_MIN


def test_no_warp_without_a_figure():
    from utils.body import warp_factors

    assert set(warp_factors(None, height_cm=165).values()) == {1.0}
