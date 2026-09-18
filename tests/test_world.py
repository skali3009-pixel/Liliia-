"""Мир, который растёт от того, что человек и так делает."""

import pytest

from utils.world import ZONES, build, headline, next_unlock, stage_of


def world(**facts):
    return build(facts)


# --- Ступени ---------------------------------------------------------------

def test_a_new_world_is_closed_but_visible():
    """Закрытое место видно: человек должен знать, что впереди."""
    states = world()
    assert all(not zone.open for zone in states)
    assert all(zone.hint.startswith("Откроется") for zone in states)


def test_the_first_diary_entry_opens_the_garden():
    """Первая запись — росток. Ровно то, о чём просили."""
    garden = world(diary_days=1)[0]
    assert garden.open and garden.title == "Росток"


def test_a_place_grows_step_by_step():
    stages = [world(diary_days=days)[0].title
              for days in (0, 1, 7, 21, 60, 200)]
    assert stages == ["Сад", "Росток", "Грядка", "Сад", "Цветущий сад",
                      "Цветущий сад"]


def test_a_grown_place_says_so_instead_of_asking_for_more():
    zone = world(diary_days=500)[0]
    assert zone.maxed and zone.hint == "Выросло полностью"


@pytest.mark.parametrize("zone", ZONES)
def test_every_place_has_four_steps_and_rising_thresholds(zone):
    assert len(zone.stages) == len(zone.thresholds) == 4
    assert list(zone.thresholds) == sorted(zone.thresholds)
    assert len(set(zone.thresholds)) == 4


# --- Логово: про мир целиком ----------------------------------------------

def test_the_den_does_not_open_first():
    """Логово — награда за выросший мир, а не стартовое место."""
    early = {state.zone.code: state for state in world(diary_days=1, streak=3)}
    assert not early["den"].open

    grown = {state.zone.code: state
             for state in world(diary_days=25, water_days=12, workout_days=8,
                                measurements=5, streak=20, level=6,
                                weight_lost_kg=3)}
    assert grown["den"].open


# --- Ближайшее открытие ----------------------------------------------------

def test_the_closest_unlock_is_measured_in_days_not_shares():
    """«Ещё один замер» и «ещё один уровень» — это неделя и пара дней.

    По долям они выглядят одинаково, и без пересчёта в дни человеку
    показывали бы недостижимое.
    """
    # У новичка уровень уже первый, то есть до второго «половина пути» —
    # но это целый день стараний, а сад открывается одной записью еды.
    assert next_unlock(world()).zone.code == "garden"
    assert next_unlock(world(diary_days=4, water_days=2)).zone.code == "lake"


def test_closed_places_matter_more_than_another_step():
    """Новое место заметнее, чем очередная ступень знакомого."""
    states = world(diary_days=6, water_days=2)
    assert not next_unlock(states).open


def test_a_finished_world_has_nothing_left_to_promise():
    states = world(diary_days=999, water_days=999, workout_days=999,
                   measurements=999, streak=999, level=99, weight_lost_kg=99)
    assert next_unlock(states) is None


# --- Тон -------------------------------------------------------------------

def test_an_empty_world_invites_instead_of_scolding():
    """Мир не отбирают за пропуски — он ждёт."""
    title, subtitle = headline(world())
    assert "Пустая долина" == title
    for shame in ("потерял", "пропустил", "не смог", "провал"):
        assert shame not in subtitle.lower()


def test_headline_grows_with_the_world():
    assert headline(world())[0] == "Пустая долина"
    assert headline(world(diary_days=2))[0] == "Твой мир"
    full = world(diary_days=999, water_days=999, workout_days=999,
                 measurements=999, streak=999, level=99, weight_lost_kg=99)
    assert headline(full)[0] == "Полный мир"


def test_numbers_are_spoken_in_russian():
    """«1 дней» выдаёт машину с головой."""
    hints = [zone.hint for zone in world(water_days=2, diary_days=6, level=1)]
    joined = " ".join(hints)
    for wrong in ("1 дней", "1 замеров", "1 тренировок", "2 уровень", "1 ступеней"):
        assert wrong not in joined, f"неверное окончание: {wrong}"


def test_progress_share_stays_within_bounds():
    for days in range(0, 80, 3):
        for zone in world(diary_days=days, water_days=days, streak=days):
            assert 0.0 <= zone.share <= 1.0


def test_stage_counting_is_monotonic():
    zone = ZONES[0]
    seen = [stage_of(zone, value) for value in range(0, 90)]
    assert seen == sorted(seen)


def test_a_weekly_thing_is_not_called_closer_than_a_daily_one():
    """Замер раз в неделю не может быть «ближе», чем запись еды сегодня."""
    states = {zone.zone.code: zone for zone in world()}
    assert states["observatory"].days_left > states["garden"].days_left
    assert states["temple"].days_left > states["lake"].days_left
