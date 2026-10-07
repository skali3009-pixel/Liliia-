"""Учёт «Первой недели»: люди по неделе прихода, попытка отдельно от дела.

Решение 27.09: считать уникальных людей, а не нажатия; отличать попытку от
успешного действия; не класть в учёт ни еды, ни веса, ни аллергий, ни
отметок цикла — даже сам факт отметки цикла.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from models import MarketingEvent, Meal, MealSourceEnum, MealTypeEnum, WorkoutLog
from services import analytics
from tests.test_webapp_api import OTHER_ID, USER_ID, call, maker_holder, webapp_client


def run(scenario):
    asyncio.run(scenario())


async def mark(session, user_id, event, day, kind=""):
    session.add(MarketingEvent(user_id=user_id, event=event, kind=kind, day=day, count=1))


def test_a_cohort_counts_people_and_separates_attempts_from_results():
    async def scenario():
        async with webapp_client() as (client, _):
            today = analytics._today()
            async with maker_holder["maker"]() as session:
                # Оба дошли до конца анкеты сегодня.
                for uid in (USER_ID, OTHER_ID):
                    await mark(session, uid, analytics.ONBOARDING_STARTED, today)
                    await mark(session, uid, analytics.PROFILE_COMPLETED, today)
                # Второй только пробовал записать еду и открыл тренировку.
                await mark(session, OTHER_ID, analytics.MEAL_ATTEMPT, today)
                await mark(session, OTHER_ID, analytics.WORKOUT_STARTED, today)
                # Первый тоже пробовал — и записал (запись заведена фикстурой).
                await mark(session, USER_ID, analytics.MEAL_ATTEMPT, today)
                # Первый вернулся на следующий день.
                await mark(session, USER_ID, analytics.ACTIVE_DAY, today + timedelta(days=1))
                await mark(session, USER_ID, analytics.WEEK_INTEREST, today)
                await session.commit()

            async with maker_holder["maker"]() as session:
                [*_, week] = await analytics.cohorts(session)
            assert week["started"] == 2 and week["completed"] == 2
            # Запись еды у первого есть (заведена фикстурой), у второго — нет.
            assert week["first_meal_7d"] == 1
            assert week["meal_attempt_7d"] == 2   # пробовали двое, записал один
            assert week["workout_started_7d"] == 1 and week["first_workout_7d"] == 0
            assert week["returned_2_7"] == 1
            assert week["week_interest"] == 1
            assert week["complete"] is False
    run(scenario)


def test_an_undone_meal_is_not_a_first_meal():
    async def scenario():
        async with webapp_client() as (client, meal_id):
            today = analytics._today()
            async with maker_holder["maker"]() as session:
                await mark(session, USER_ID, analytics.PROFILE_COMPLETED, today)
                await session.commit()
            await call(client, "DELETE", f"/api/meals/{meal_id}")
            async with maker_holder["maker"]() as session:
                [*_, week] = await analytics.cohorts(session)
            assert week["completed"] == 1 and week["first_meal_7d"] == 0
    run(scenario)


def test_owners_are_left_out():
    async def scenario():
        async with webapp_client():
            today = analytics._today()
            async with maker_holder["maker"]() as session:
                await mark(session, USER_ID, analytics.PROFILE_COMPLETED, today)
                await session.commit()
                [*_, week] = await analytics.cohorts(session, exclude={USER_ID})
            assert week["completed"] == 0
    run(scenario)


def test_the_app_can_mark_only_what_is_on_the_list():
    async def scenario():
        async with webapp_client() as (client, _):
            ok = await call(client, "POST", "/api/track", json_body={"event": "meal_attempt"})
            assert ok.status == 200
            again = await call(client, "POST", "/api/track", json_body={"event": "meal_attempt"})
            assert again.status == 200
            for bad in ("cycle_marked", "weight_85", "profile_completed", ""):
                response = await call(client, "POST", "/api/track", json_body={"event": bad})
                assert response.status == 400, bad
            async with maker_holder["maker"]() as session:
                rows = (await session.execute(select(MarketingEvent).where(
                    MarketingEvent.event == analytics.MEAL_ATTEMPT))).scalars().all()
            # Раз в день — одна строка и одно событие, а не два нажатия.
            assert len(rows) == 1 and rows[0].count == 1
    run(scenario)


def test_no_event_speaks_about_the_body():
    """Ни цикла, ни веса, ни еды, ни аллергий — ни в кодах, ни в списке
    того, что приложение может отметить само."""
    codes = [value for name, value in vars(analytics).items()
             if name.isupper() and isinstance(value, str) and "_" in value]
    codes += list(analytics.CLIENT_EVENTS)
    for code in codes:
        for word in ("cycle", "period", "weight", "allerg", "food_name"):
            assert word not in code, code


def test_the_owner_report_names_people_and_explains_itself():
    from handlers.access import первая_неделя

    lines = первая_неделя([{
        "week": analytics._today(), "started": 3, "completed": 2,
        "meal_attempt_7d": 2, "first_meal_7d": 1, "workout_started_7d": 1,
        "first_workout_7d": 1, "returned_2_7": 1, "weekly_opened": 0,
        "week_interest": 0, "complete": False}])
    assert "начали анкету 3, закончили 2" in lines[0]
    assert "(идёт)" in lines[0]
    assert "число людей, не нажатий" in lines[-1]


def test_the_weekly_summary_shows_what_there_is_and_blames_no_cycle():
    from services.weekly import WeeklySummary, render

    only_workouts = WeeklySummary(user_id=1, days_logged=0, avg_calories=0, norm_calories=1600,
                                  weight_from=None, weight_to=None, workouts=2,
                                  water_days=0)
    text = render(only_workouts)
    assert "Тренировок: 2" in text and "пусто" not in text
    heavier = WeeklySummary(user_id=1, days_logged=5, avg_calories=1500, norm_calories=1600,
                            weight_from=60.0, weight_to=61.0, workouts=0, water_days=0)
    assert "цикл" not in render(heavier, goal="lose_weight")


def test_the_weekly_summary_asks_about_interest_without_selling():
    async def scenario():
        from handlers.notifications import WEEK_INTEREST_REPLY, week_interest
        from keyboards.notifications import CB_WEEK_INTEREST, weekly_keyboard
        from tests.test_offer_is_not_meal import Callback
        import handlers.notifications as notif
        import db as db_module

        buttons = [b for row in weekly_keyboard().inline_keyboard for b in row]
        assert any(b.callback_data == CB_WEEK_INTEREST for b in buttons)
        assert "Ничего платного" in WEEK_INTEREST_REPLY
        for word in ("₽", "руб", "Stars", "подписк", "цена"):
            assert word not in WEEK_INTEREST_REPLY

        async with webapp_client():
            original = notif.get_session
            notif.get_session = db_module.get_session
            try:
                await week_interest(Callback(CB_WEEK_INTEREST))
                await week_interest(Callback(CB_WEEK_INTEREST))
            finally:
                notif.get_session = original
            async with maker_holder["maker"]() as session:
                rows = (await session.execute(select(MarketingEvent).where(
                    MarketingEvent.event == analytics.WEEK_INTEREST))).scalars().all()
            assert len(rows) == 1 and rows[0].count == 1
    run(scenario)


def test_a_workout_is_counted_from_the_log_itself():
    async def scenario():
        async with webapp_client():
            today = analytics._today()
            async with maker_holder["maker"]() as session:
                from seed.loader import seed_workouts
                from models import Workout

                await seed_workouts(session)
                workout = (await session.execute(select(Workout).limit(1))).scalar_one()
                await mark(session, OTHER_ID, analytics.PROFILE_COMPLETED, today)
                session.add(WorkoutLog(user_id=OTHER_ID, workout_id=workout.id,
                                       duration_minutes=5, calories_burned=20))
                session.add(Meal(user_id=OTHER_ID, name="x", calories=1,
                                 source=MealSourceEnum.TEXT, meal_type=MealTypeEnum.SNACK))
                await session.commit()
                [*_, week] = await analytics.cohorts(session)
            assert week["first_workout_7d"] == 1
    run(scenario)


def test_the_chat_card_marks_an_attempt_and_the_questionnaire_marks_its_start():
    async def scenario():
        from handlers.food import _show_card
        from handlers.onboarding import begin_onboarding
        from services.food_vision import FoodAnalysis
        from tests.test_offer_is_not_meal import Message, State
        import handlers.food as food
        import handlers.onboarding as onboarding
        import db as db_module
        from models import User

        async with webapp_client():
            async with maker_holder["maker"]() as session:
                user = await session.get(User, OTHER_ID)
                user.onboarding_completed = False
                await session.commit()
            saved = food.get_session, onboarding.get_session
            food.get_session = onboarding.get_session = db_module.get_session
            try:
                message = Message(USER_ID)
                message.chat = type("C", (), {"id": USER_ID})()
                await _show_card(message, State(), FoodAnalysis(
                    name="x", weight_g=100, calories=100, protein_g=1, fat_g=1,
                    carbs_g=1, fiber_g=0, confidence="medium", comment=""),
                    photo_file_id=None)
                await begin_onboarding(Message(OTHER_ID), State(), OTHER_ID)
            finally:
                food.get_session, onboarding.get_session = saved
            async with maker_holder["maker"]() as session:
                events = {(row.user_id, row.event) for row in (await session.execute(
                    select(MarketingEvent))).scalars()}
            assert (USER_ID, analytics.MEAL_ATTEMPT) in events
            assert (OTHER_ID, analytics.ONBOARDING_STARTED) in events
    run(scenario)


# --- Путь «Первая неделя» ------------------------------------------------

def test_after_the_questionnaire_there_is_a_choice_of_food_or_movement(monkeypatch):
    import config
    from handlers.onboarding import CB_FIRST_MEAL, first_step_keyboard, first_step_text

    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.com")
    buttons = [b for row in first_step_keyboard().inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["📷 Записать еду", "🏃 Короткая тренировка"]
    assert buttons[0].callback_data == CB_FIRST_MEAL
    assert buttons[1].web_app.url == "https://example.com?screen=gym"
    assert not [b for b in buttons if b.url or "SCALIA" in b.text]
    # Без приложения — тоже две кнопки, а не пустая клавиатура.
    monkeypatch.setattr(config, "WEBAPP_URL", "")
    assert len([b for row in first_step_keyboard().inline_keyboard for b in row]) == 2
    text = first_step_text()
    assert "выбери одно" in text and "оценка" in text
    # Никаких обещаний точности или скорости.
    for promise in ("точно", "секунд", "похуде", "кг"):
        assert promise not in text.lower(), promise


def test_the_food_choice_opens_the_same_food_input_as_the_menu_button():
    async def scenario():
        from handlers.food import FOOD_PROMPT, first_meal_choice
        from handlers.onboarding import CB_FIRST_MEAL
        from states.food import FoodStates
        from tests.test_offer_is_not_meal import Callback, State

        state = State()
        press = Callback(CB_FIRST_MEAL)
        await first_meal_choice(press, state)
        assert state.state == FoodStates.waiting_input
        assert press.message.said[-1] == FOOD_PROMPT
    run(scenario)


def test_the_questionnaire_ends_with_the_first_action_and_keeps_music_optional():
    import inspect
    import handlers.onboarding as onboarding

    body = inspect.getsource(onboarding._finish_onboarding)
    assert "first_step_keyboard(interest)" in body
    assert "music.отправить" not in body
    assert body.strip().endswith("await message.answer(first_step_text(interest), reply_markup=first_step_keyboard(interest))")


def test_the_first_meal_gets_one_calm_line_and_the_second_does_not():
    async def scenario():
        from handlers.food import FIRST_MEAL_NOTE
        from tests.test_food_saving import ANALYSIS, database
        from tests.test_offer_is_not_meal import Callback, State, save

        async with database():
            first = await save(State({"analysis": ANALYSIS.to_dict()}))
            second = await save(State({"analysis": ANALYSIS.to_dict()}))
        assert first.message.said[-1].endswith(FIRST_MEAL_NOTE)
        assert FIRST_MEAL_NOTE not in second.message.said[-1]
    run(scenario)


def test_the_first_workout_is_named_as_first_once():
    async def scenario():
        from seed.loader import seed_workouts
        import webapp.api as api_module

        async with webapp_client() as (client, _):
            async with api_module.get_session() as session:
                await seed_workouts(session)
            data = await (await call(client, "GET", "/api/workouts")).json()
            ids = [data["exercises"][0]["id"]]
            one = await (await call(client, "POST", "/api/workouts/log",
                                    json_body={"exercise_ids": ids})).json()
            two = await (await call(client, "POST", "/api/workouts/log",
                                    json_body={"exercise_ids": ids})).json()
            assert one["first"] is True and two["first"] is False
    run(scenario)
