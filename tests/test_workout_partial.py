"""«58 ккал за одну минуту»: проводник записывал упражнение целиком после
первого подхода.

Упражнение попадало в «сделанные», как только кончался его первый подход,
а сервер записывал все запланированные подходы — с их минутами и расходом.
Экран итога при этом показывал честное время с часов: одну минуту. Отсюда
и цифра, которой не бывает. Теперь проводник присылает, сколько подходов
правда сделано, и расход считается в той же доле.
"""

import asyncio
import pathlib

from sqlalchemy import select

from models import WorkoutLog
from tests.test_webapp_api import call, maker_holder, webapp_client


def run(scenario):
    asyncio.run(scenario())


async def _exercise(client):
    from seed.loader import seed_workouts
    import webapp.api as api_module

    async with api_module.get_session() as session:
        await seed_workouts(session)
    data = await (await call(client, "GET", "/api/workouts")).json()
    return next(e for e in data["exercises"] if (e["sets"] or 0) >= 3 and not e["is_cardio"])


async def _log(client, body):
    return await (await call(client, "POST", "/api/workouts/log", json_body=body)).json()


def test_one_set_of_three_is_a_third_of_the_exercise():
    async def scenario():
        async with webapp_client() as (client, _):
            item = await _exercise(client)
            full = await _log(client, {"exercise_ids": [item["id"]]})
            part = await _log(client, {"exercise_ids": [item["id"]],
                                       "sets": {str(item["id"]): 1}})

            share = 1 / item["sets"]
            assert abs(part["calories"] - full["calories"] * share) <= 1
            assert abs(part["minutes"] - full["minutes"] * share) <= 0.2

            async with maker_holder["maker"]() as session:
                logs = (await session.execute(
                    select(WorkoutLog).order_by(WorkoutLog.id))).scalars().all()
            assert [log.sets_done for log in logs] == [item["sets"], 1]
    run(scenario)


def test_without_the_count_everything_is_as_before():
    """Отметка из каталога и тренировка, сохранённая старой версией
    приложения, счёта подходов не присылают — и считаются целиком."""
    async def scenario():
        async with webapp_client() as (client, _):
            item = await _exercise(client)
            before = await _log(client, {"exercise_ids": [item["id"]]})
            also = await _log(client, {"exercise_ids": [item["id"]], "sets": None})
            assert before["calories"] == also["calories"] > 0
    run(scenario)


def test_the_count_cannot_inflate_the_exercise():
    async def scenario():
        async with webapp_client() as (client, _):
            item = await _exercise(client)
            full = await _log(client, {"exercise_ids": [item["id"]]})
            more = await _log(client, {"exercise_ids": [item["id"]],
                                       "sets": {str(item["id"]): 99}})
            junk = await _log(client, {"exercise_ids": [item["id"]],
                                       "sets": {str(item["id"]): "много", "x": 1}})
            assert more["calories"] == full["calories"]
            assert junk["calories"] == full["calories"]
    run(scenario)


def test_the_player_counts_sets_and_sends_them():
    app = pathlib.Path("webapp/static/app.js").read_text(encoding="utf-8")
    advance = app.split("function advance()", 1)[1].split("\n}", 1)[0]
    assert "player.sets[item.id] = (player.sets[item.id] || 0) + 1" in advance
    finish = app.split("async function finishPlayer()", 1)[1].split("\n}", 1)[0]
    assert "sets: player.sets || null" in finish
    assert "done: [], sets: {}," in app
