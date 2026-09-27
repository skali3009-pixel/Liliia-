"""Мелочи доверия с записи экрана 26.09: вес из анкеты и пустой квадрат показа."""

import asyncio
import pathlib

from tests.test_webapp_api import USER_ID, call, maker_holder, webapp_client

APP = pathlib.Path("webapp/static/app.js").read_text(encoding="utf-8")


def run(scenario):
    asyncio.run(scenario())


def test_weight_from_the_questionnaire_is_named_as_such_until_the_first_weighing():
    async def scenario():
        async with webapp_client() as (client, _):
            data = await (await call(client, "GET", "/api/progress")).json()
            assert data["summary"]["from_questionnaire"] is True
            assert data["points"] == []
            await call(client, "POST", "/api/measurements", json_body={"weight_kg": 59.5})
            data = await (await call(client, "GET", "/api/progress")).json()
            assert data["summary"]["from_questionnaire"] is False
    run(scenario)


def test_the_empty_chart_explains_the_questionnaire_weight():
    body = APP.split("function buildChart(", 1)[1].split("\n}", 1)[0]
    assert "from_questionnaire" in body
    assert "исходное значение" in body


def test_the_trainer_square_says_it_is_loading_instead_of_staying_blank():
    body = APP.split("function ExerciseTrainerAnimation(", 1)[1].split("\n}", 1)[0]
    assert "Загружаю показ…" in body
    assert "loadeddata" in body and "wait.remove()" in body
    assert "Показ не загрузился" in body
    css = pathlib.Path("webapp/static/styles.css").read_text(encoding="utf-8")
    assert ".media-wait" in css
