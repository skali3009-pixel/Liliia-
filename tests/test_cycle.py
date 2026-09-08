"""Женский календарь.

Он здесь не ради календаря — таких приложений и без нас хватает. Он здесь
ради одной строки, которую больше некому сказать: вес перед месячными выше
не потому, что человек что-то сделал не так. Поэтому проверок про вес тут
столько же, сколько про сами дни.

И столько же — про осторожность: календарь не должен показываться тому,
кто его не заводил, не должен обещать даты и не должен притворяться
средством контрацепции.
"""

import asyncio
import contextlib
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, GenderEnum, GoalEnum, User
from services import cycle

TODAY = date(2026, 9, 8)


def days_ago(*offsets):
    return [TODAY - timedelta(days=n) for n in offsets]


# --- какой сегодня день ---------------------------------------------------


def test_nothing_marked_means_nothing_is_claimed():
    state = cycle.build([], TODAY)
    assert not state.known
    assert state.next_start is None and state.average_length is None


def test_the_first_day_is_day_one():
    assert cycle.build(days_ago(0), TODAY).day == 1
    assert cycle.build(days_ago(2), TODAY).day == 3


def test_the_phase_follows_the_day():
    long_enough = days_ago(0, 28, 56)
    for offset, expected in ((0, "period"), (3, "period"), (8, "after"),
                             (16, "middle"), (25, "before")):
        starts = [TODAY - timedelta(days=offset)] + days_ago(28 + offset, 56 + offset)
        assert cycle.build(starts, TODAY).phase.code == expected, offset
    assert cycle.build(long_enough, TODAY).phase.code == "period"


def test_someone_who_stopped_marking_is_not_given_a_made_up_day():
    """Полгода назад — не «день 183 цикла», а «не знаю»."""
    state = cycle.build(days_ago(180), TODAY)
    assert not state.known
    assert state.phase is None


# --- средняя длина и оценка ------------------------------------------------


def test_an_average_needs_at_least_two_marks():
    assert cycle.average_length(days_ago(0)) is None
    assert cycle.average_length(days_ago(0, 28)) == 28


def test_a_missed_mark_does_not_poison_the_average():
    """Пропущенная отметка даёт «цикл» в 56 дней.

    Взяв его в среднее, календарь сдвинул бы все оценки — и сломался бы
    именно там, где человек и так сбился.
    """
    assert cycle.lengths(days_ago(0, 56, 84)) == [28]
    assert cycle.average_length(days_ago(0, 56, 84)) == 28


def test_the_forecast_is_an_estimate_and_says_so():
    state = cycle.build(days_ago(0, 28, 56), TODAY)
    assert state.next_start == TODAY + timedelta(days=28)
    assert state.days_to_next == 28
    assert "не средство контрацепции" in cycle.DISCLAIMER


def test_one_mark_gives_no_forecast():
    """Обещать дату по одной отметке — значит выдумывать."""
    assert cycle.build(days_ago(1), TODAY).next_start is None


def test_the_average_is_the_persons_own_not_a_textbook_one():
    short = cycle.build(days_ago(0, 24, 48), TODAY)
    assert short.average_length == 24
    assert short.next_start == TODAY + timedelta(days=24)


def test_only_the_recent_cycles_count():
    """Год назад человек мог жить совсем иначе."""
    many = days_ago(*[n * 28 for n in range(12)])
    assert cycle.average_length(many) == 28
    assert len(cycle.lengths(many)[-cycle.RECENT:]) == cycle.RECENT


# --- ради чего всё затевалось ---------------------------------------------


def test_the_weight_before_the_period_is_explained():
    """Самая частая причина бросить — плюс полтора килограмма без причины."""
    state = cycle.build(days_ago(24, 52, 80), TODAY)
    assert state.phase.code == "before"

    note = cycle.weight_note(state, latest_kg=62.4, usual_kg=61.0)
    assert note is not None
    assert "1,4 кг" in note        # по-русски запятая
    assert note.endswith("уходит сама.")   # и точка на месте
    assert "не жир" in note


def test_a_small_difference_is_not_worth_saying():
    """Полкило — это время суток и весы, а не цикл."""
    state = cycle.build(days_ago(24, 52, 80), TODAY)
    assert cycle.weight_note(state, latest_kg=61.1, usual_kg=61.0) is None


def test_nothing_is_said_in_the_middle_of_the_cycle():
    state = cycle.build(days_ago(14, 42, 70), TODAY)
    assert state.phase.code in {"after", "middle"}
    assert cycle.weight_note(state, latest_kg=62.5, usual_kg=61.0) is None


def test_without_numbers_nothing_is_invented():
    state = cycle.build(days_ago(24, 52, 80), TODAY)
    assert cycle.weight_note(state, latest_kg=None, usual_kg=61.0) is None
    assert cycle.weight_note(state, latest_kg=62.4, usual_kg=None) is None


def test_the_wording_promises_nothing_and_diagnoses_nothing():
    # Запрещено суждение о цикле и обещание, а не отдельное слово.
    # «Это нормально» про усталость — ровно то доброе, что здесь и нужно;
    # «твой цикл в норме» — вывод, которого мы делать не вправе.
    forbidden = ("цикл в норме", "нерегуляр", "нарушен", "патолог",
                 "заболев", "лечит", "безопасные дни", "забереме", "диагноз")
    texts = [phase.title + " " + phase.note for phase in cycle.PHASES.values()]
    texts.append(cycle.DISCLAIMER)
    state = cycle.build(days_ago(24, 52, 80), TODAY)
    texts.append(cycle.weight_note(state, latest_kg=62.4, usual_kg=61.0) or "")
    for text in texts:
        low = text.lower()
        for word in forbidden:
            assert word not in low, text


# --- база -----------------------------------------------------------------


@contextlib.asynccontextmanager
async def db(**overrides):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        fields = dict(id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165,
                      current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                      onboarding_completed=True, timezone="Europe/Moscow")
        fields.update(overrides)
        session.add(User(**fields))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def test_marking_and_unmarking_the_same_day():
    """Промахнуться по дате легко. Календарь, из которого нельзя убрать
    ошибку, начинает врать навсегда."""
    async def scenario():
        async with db() as session:
            assert await cycle.mark(session, 1, TODAY) is True
            assert await cycle.all_starts(session, 1) == [TODAY]

            assert await cycle.mark(session, 1, TODAY) is False
            assert await cycle.all_starts(session, 1) == []
    run(scenario)


def test_the_state_comes_back_from_the_database():
    async def scenario():
        async with db() as session:
            for day in days_ago(2, 30, 58):
                await cycle.mark(session, 1, day)
            state = await cycle.state(session, 1, TODAY)
            assert state.day == 3
            assert state.average_length == 28
    run(scenario)


# --- кому его видно -------------------------------------------------------


def test_the_calendar_is_only_for_those_who_want_it():
    """Мужчине он бессмыслен, а женщине может быть просто не нужен.

    Показать его всем — значит начать разговор о теле, которого человек
    не начинал.
    """
    from webapp.api import _cycle_shown

    class Fake:
        def __init__(self, gender, enabled=True):
            self.gender, self.cycle_enabled = gender, enabled

    assert _cycle_shown(Fake(GenderEnum.FEMALE))
    assert not _cycle_shown(Fake(GenderEnum.MALE))
    assert not _cycle_shown(Fake(GenderEnum.FEMALE, enabled=False))
    assert not _cycle_shown(None)


def test_the_usual_weight_ignores_today():
    """Сегодняшний вес — то, что проверяется. В «обычный» он попасть не может."""
    from webapp.api import _usual_weight

    class Point:
        def __init__(self, day, value):
            self.day, self.value = day, value

    points = [Point(TODAY - timedelta(days=n), 61.0) for n in (12, 20, 30)]
    points.append(Point(TODAY, 63.0))
    assert _usual_weight(points, TODAY) == 61.0


def test_the_usual_weight_is_the_middle_not_the_average():
    """Один промах весов не должен сдвигать всю картину."""
    from webapp.api import _usual_weight

    class Point:
        def __init__(self, day, value):
            self.day, self.value = day, value

    values = [61.0, 61.2, 61.1, 75.0]      # последний — явная ошибка
    points = [Point(TODAY - timedelta(days=12 + i), v)
              for i, v in enumerate(values)]
    assert _usual_weight(points, TODAY) < 62


def test_the_privacy_policy_names_the_new_data():
    """Новый вид данных обязан быть в таблице политики, иначе она врёт."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "legal" / "privacy.html").read_text(
        encoding="utf-8")
    assert "месячных" in text
    assert "выключить" in text          # и сказано, что от него можно отказаться
