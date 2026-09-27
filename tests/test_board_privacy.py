"""Общая таблица шагов: псевдоним по умолчанию, имя — по выбору, выход — без потерь.

На записи экрана 26.09 «Неделя приложения» показывала настоящее имя другого
человека каждому, кто открыл приложение, — без его ведома. А в ответ
уходил ещё и номер в Telegram. Решение 27.09: по умолчанию псевдоним, имя —
только если человек сам выбрал, и из таблицы можно выйти, не удаляя дневник.
"""

import asyncio

from sqlalchemy import select

from models import BoardPrefs, StepLog
from tests.test_webapp_api import OTHER_ID, USER_ID, call, maker_holder, webapp_client


def run(scenario):
    asyncio.run(scenario())


async def board(client, user_id=USER_ID):
    return await (await call(client, "GET", "/api/steps/board", user_id=user_id)).json()


async def walk(client):
    await call(client, "POST", "/api/steps", json_body={"steps": 7000})
    await call(client, "POST", "/api/steps", json_body={"steps": 9000}, user_id=OTHER_ID)


def test_strangers_see_a_pseudonym_not_a_name_and_no_telegram_number():
    async def scenario():
        from services.board_privacy import pseudonym

        async with webapp_client() as (client, _):
            await walk(client)
            data = await board(client)
            other = next(row for row in data["top"] if not row["me"])
            assert other["name"] == pseudonym(OTHER_ID)
            assert "Лилия" not in other["name"]
            assert all("user_id" not in row for row in data["top"])
            assert data["privacy"] == {"show_name": False, "hidden": False,
                                       "pseudonym": pseudonym(USER_ID)}
    run(scenario)


def test_the_name_is_shown_only_after_the_person_chooses_it():
    async def scenario():
        async with webapp_client() as (client, _):
            await walk(client)
            response = await call(client, "POST", "/api/steps/board/prefs",
                                  json_body={"show_name": True}, user_id=OTHER_ID)
            assert (await response.json())["show_name"] is True
            other = next(row for row in (await board(client))["top"] if not row["me"])
            assert other["name"] == "Лилия"
    run(scenario)


def test_leaving_the_board_hides_you_from_others_but_keeps_your_steps():
    async def scenario():
        async with webapp_client() as (client, _):
            await walk(client)
            await call(client, "POST", "/api/steps/board/prefs",
                       json_body={"hidden": True}, user_id=OTHER_ID)
            assert all(row["me"] for row in (await board(client))["top"])
            # Сам себя человек видит, и шаги его на месте.
            own = await board(client, user_id=OTHER_ID)
            assert own["privacy"]["hidden"] is True
            async with maker_holder["maker"]() as session:
                steps = (await session.execute(select(StepLog).where(
                    StepLog.user_id == OTHER_ID))).scalars().all()
            assert steps and steps[0].steps == 9000
    run(scenario)


def test_the_pseudonym_is_stable_and_reveals_nothing():
    from services.board_privacy import pseudonym

    assert pseudonym(4242) == pseudonym(4242)
    assert pseudonym(4242) != pseudonym(777)
    assert "4242" not in pseudonym(4242)


def test_deleting_the_person_removes_the_setting():
    async def scenario():
        from services.deletion import purge

        async with webapp_client() as (client, _):
            await call(client, "POST", "/api/steps/board/prefs",
                       json_body={"show_name": True}, user_id=OTHER_ID)
            async with maker_holder["maker"]() as session:
                await purge(session, OTHER_ID)
                assert await session.get(BoardPrefs, OTHER_ID) is None
    run(scenario)
