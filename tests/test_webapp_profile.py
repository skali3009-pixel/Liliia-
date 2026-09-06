"""Правка профиля из мини-приложения: те же проверки, что и в чате."""

from models import ActivityLevelEnum, GoalEnum, User
from tests.test_webapp_api import OTHER_ID, USER_ID, call, run, webapp_client


async def load(client, user_id=USER_ID):
    response = await call(client, "GET", "/api/profile", user_id=user_id)
    assert response.status == 200
    return await response.json()


async def patch(client, body, user_id=USER_ID):
    return await call(client, "PATCH", "/api/profile", user_id=user_id, json_body=body)


def test_profile_returns_fields_options_and_limits():
    async def scenario():
        async with webapp_client() as (client, _):
            data = await load(client)
            assert data["profile"]["goal"] == "lose_weight"
            assert data["profile"]["height_cm"] == 165
            assert data["profile"]["reminders"] is True
            assert data["norms"]["calories"] == 1600
            # Подписи приходят с сервера: в приложении не должно быть второй
            # копии переводов, которая разойдётся с ботом.
            goals = {item["code"]: item["label"] for item in data["options"]["goal"]}
            assert goals["lose_weight"] == "похудение"
            assert data["limits"]["age"] == [10, 100]
    run(scenario)


def test_changing_the_goal_recalculates_the_norm():
    async def scenario():
        async with webapp_client() as (client, _):
            # Без уровня активности норму не из чего считать — сначала он.
            before = (await (await patch(client, {"activity": "moderate"})).json()
                      )["norms"]["calories"]
            response = await patch(client, {"goal": "gain_mass"})
            assert response.status == 200
            data = await response.json()
            assert data["profile"]["goal"] == "gain_mass"
            assert data["recalculated"] is True
            assert data["norms"]["calories"] != before
            # Ответ и база должны совпадать, а не только выглядеть верно.
            assert (await load(client))["norms"]["calories"] == data["norms"]["calories"]
    run(scenario)


def test_a_goal_change_survives_an_unfinished_profile():
    """У анкеты без активности норму считать не из чего — но правка проходит."""
    async def scenario():
        async with webapp_client() as (client, _):
            data = await (await patch(client, {"goal": "maintain"})).json()
            assert data["profile"]["goal"] == "maintain"
            assert data["recalculated"] is False
            assert data["norms"]["calories"] == 1600
    run(scenario)


def test_diet_is_saved_without_touching_the_norm():
    async def scenario():
        async with webapp_client() as (client, _):
            before = (await load(client))["norms"]["calories"]
            data = await (await patch(client, {"diet": "vegan"})).json()
            assert data["profile"]["diet"] == "vegan"
            assert data["recalculated"] is False
            assert data["norms"]["calories"] == before
    run(scenario)


def test_activity_and_height_together_recalculate_once():
    async def scenario():
        async with webapp_client() as (client, _):
            data = await (await patch(client, {"activity": "high", "height": "170,5"})).json()
            assert data["profile"]["activity"] == "high"
            # Запятая — обычный способ написать дробное число на телефоне.
            assert data["profile"]["height_cm"] == 170.5
            assert data["recalculated"] is True
    run(scenario)


def test_impossible_values_are_rejected_with_a_readable_reason():
    async def scenario():
        async with webapp_client() as (client, _):
            for body in ({"age": 3}, {"height": 40}, {"target_weight": 500},
                         {"age": "позавчера"}, {"goal": "стать драконом"}):
                response = await patch(client, body)
                assert response.status == 400, body
                assert (await response.json())["error"]
            # Ничего из отвергнутого не попало в базу.
            data = await load(client)
            assert data["profile"]["age"] == 30
            assert data["profile"]["goal"] == "lose_weight"
    run(scenario)


def test_unknown_and_empty_changes_are_refused():
    async def scenario():
        async with webapp_client() as (client, _):
            assert (await patch(client, {})).status == 400
            # Вес меняется замером — через настройки его подменить нельзя.
            response = await patch(client, {"weight_kg": 50})
            assert response.status == 400
            assert "weight_kg" in (await response.json())["error"]
    run(scenario)


def test_allergies_understand_a_plain_no():
    async def scenario():
        async with webapp_client() as (client, _):
            assert (await (await patch(client, {"allergies": "орехи, лактоза"})).json()
                    )["profile"]["allergies"] == "орехи, лактоза"
            assert (await (await patch(client, {"allergies": "нет"})).json()
                    )["profile"]["allergies"] == ""
    run(scenario)


def test_reminders_can_be_switched_off_from_the_app():
    async def scenario():
        async with webapp_client() as (client, _):
            data = await (await patch(client, {"reminders": False})).json()
            assert data["profile"]["reminders"] is False
            assert (await load(client))["profile"]["reminders"] is False
    run(scenario)


def test_editing_touches_only_your_own_profile():
    async def scenario():
        async with webapp_client() as (client, _):
            await patch(client, {"goal": "maintain"})
            assert (await load(client, OTHER_ID))["profile"]["goal"] == "lose_weight"
    run(scenario)


def test_profile_needs_a_signature():
    async def scenario():
        async with webapp_client() as (client, _):
            response = await call(client, "GET", "/api/profile", signed=False)
            assert response.status == 401
    run(scenario)
