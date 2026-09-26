"""Предложенное блюдо — не съеденное.

Раньше «✅ Съела это» под подобранным блюдом писало в дневник одним нажатием
ровно ту порцию, что посчитал подбор, с пометкой «уверенность высокая». Но
подбор знает состав, а не тарелку: человек съел половину или добавку — а в
дневнике справочная цифра, выданная за измеренную. Отменить запись из того
же места было нечем.

Теперь нажатие открывает ту же карточку, что фото и текст: вес, «≈» у
калорий, основание оценки, «меньше/больше», «Сохранить». После записи — две
кнопки под итогом: «Исправить вес» и «Отменить запись». Тесты нажимают
кнопки целиком, как человек, на настоящей базе.
"""

import asyncio

import pytest
from sqlalchemy import select

from models import DayStat, MarketingEvent, Meal
from services import analytics
from services.food_vision import FoodAnalysis
from services.menu import Offer
from tests.test_food_saving import USER_ID, FakeCallback, FakeMessage, FakeState, database


class Message(FakeMessage):
    """Помнит и клавиатуры: по ним видно, что предложено после записи."""

    def __init__(self, user_id: int = USER_ID):
        super().__init__()
        self.markups: list = []
        self.edited: list[str] = []
        self.from_user = type("U", (), {"id": user_id})()
        self.message_id = 1

    async def answer(self, text, **kwargs):
        self.said.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self

    async def edit_text(self, text, **kwargs):
        self.edited.append(text)


class Callback(FakeCallback):
    def __init__(self, data: str = "", user_id: int = USER_ID):
        super().__init__(user_id)
        self.message = Message(user_id)
        self.data = data


class State(FakeState):
    def __init__(self, data: dict | None = None):
        super().__init__(data or {})
        self.state = None

    async def set_state(self, value):
        self.state = value

    async def clear(self):
        await super().clear()
        self.state = None


OFFER = Offer(
    name="Гречка с курицей", weight_g=400, calories=560, protein_g=42,
    fat_g=14, carbs_g=64, fiber_g=6, minutes=20, reason="", author=False,
)


def run(scenario):
    asyncio.run(scenario())


async def meals(maker) -> list[Meal]:
    async with maker() as session:
        return list((await session.execute(select(Meal))).scalars().all())


async def events(maker, event: str) -> int:
    async with maker() as session:
        rows = (await session.execute(
            select(MarketingEvent).where(MarketingEvent.event == event))).scalars().all()
        return sum(row.count for row in rows)


def buttons(markup) -> dict[str, str]:
    return {b.text: b.callback_data for row in markup.inline_keyboard for b in row}


@pytest.fixture
def offered(monkeypatch):
    import handlers.suggestions as sug

    monkeypatch.setitem(sug._offered, "k", OFFER)
    return "k"


async def open_card(offered: str) -> State:
    """Нажать «Записать блюдо» под подобранным вариантом."""
    import handlers.suggestions as sug
    from states.food import FoodStates

    import db as db_module

    # database() подменяет базу в модуле еды и в db; обработчик подбора
    # взял ссылку на функцию при импорте — подменяем и её.
    original = sug.get_session
    sug.get_session = db_module.get_session
    state = State()
    callback = Callback(f"{sug.CB_EAT}{offered}")
    try:
        await sug.eat_suggestion(callback, state)
    finally:
        sug.get_session = original
    assert state.state == FoodStates.confirming
    return state, callback


async def save(state: State) -> Callback:
    from handlers.food import save_food

    callback = Callback()
    await save_food(callback, state)
    return callback


def test_pressing_the_button_under_an_offer_writes_nothing(offered):
    """Главное: нажатие показывает, что будет записано, и ничего не пишет."""
    async def scenario():
        async with database() as maker:
            import handlers.suggestions as sug

            state, callback = await open_card(offered)
            assert await meals(maker) == [], "подбор записался без подтверждения"

            card = callback.message.said[-1]
            assert OFFER.name in card
            assert "400 г" in card
            # Калории — со знаком оценки и с тем, откуда они взялись.
            assert "≈ 560 ккал" in card
            assert "справочник" in card
            assert "Уверенность: высокая" not in card
            # Передумавший вернётся к варианту той же кнопкой.
            assert offered in sug._offered
            assert state.data["from_offer"] is True
    run(scenario)


def test_old_buttons_still_arrive_at_the_card(offered):
    """Данные кнопки не менялись: нажатие на старое сообщение «✅ Съела это»
    приходит туда же и тоже открывает карточку, а не пишет сразу."""
    import handlers.suggestions as sug

    assert sug.CB_EAT == "eat:"
    markup = sug._keyboard("k", with_recipe=False)
    assert list(buttons(markup).values()) == ["eat:k"]
    assert list(buttons(markup)) == ["✍️ Записать блюдо"]


def test_confirmed_offer_is_written_once_and_marked_as_from_offer(offered):
    async def scenario():
        async with database() as maker:
            state, _ = await open_card(offered)
            done = await save(state)

            written = await meals(maker)
            assert len(written) == 1
            assert written[0].calories == 560 and written[0].weight_g == 400
            # Рекомендацию теперь можно отличить от описанной самим человеком.
            assert await events(maker, analytics.MEAL_FROM_OFFER) == 1
            # Под итогом — исправить и отменить, с номером именно этой записи.
            keys = buttons(done.message.markups[-1])
            assert keys == {"⚖️ Исправить вес": f"food:fix:{written[0].id}",
                            "↩️ Отменить запись": f"food:undo:{written[0].id}"}
    run(scenario)


def test_photo_meal_is_not_counted_as_offer():
    async def scenario():
        async with database() as maker:
            analysis = FoodAnalysis(name="Суп", weight_g=300, calories=180, protein_g=8,
                                    fat_g=6, carbs_g=20, fiber_g=3, confidence="medium",
                                    comment="")
            await save(State({"analysis": analysis.to_dict(), "photo_file_id": "x"}))
            assert len(await meals(maker)) == 1
            assert await events(maker, analytics.MEAL_FROM_OFFER) == 0
    run(scenario)


def test_changing_the_portion_before_saving_rescales_everything(offered):
    async def scenario():
        from handlers.food import change_portion
        from keyboards.food import CB_LESS

        async with database() as maker:
            state, _ = await open_card(offered)

            async def no_edit(*args, **kwargs):
                return None
            # Перерисовка карточки идёт через bot.edit_message_text; здесь
            # важна не картинка, а то, что запомнено для записи.
            press = Callback(CB_LESS)
            press.message.bot = type("B", (), {"edit_message_text": staticmethod(no_edit)})()
            press.message.chat = type("C", (), {"id": USER_ID})()
            await change_portion(press, state)
            await save(state)

            [meal] = await meals(maker)
            assert meal.weight_g == 300
            assert meal.calories == pytest.approx(420)
            assert meal.protein_g == pytest.approx(31.5)
    run(scenario)


def test_undo_removes_the_meal_reopens_the_quest_and_is_counted(offered):
    async def scenario():
        from handlers.food import save_food, undo_saved

        async with database() as maker:
            # Задание «три приёма пищи» закрывается третьей записью: её и
            # отменяем — задание обязано открыться обратно.
            for _ in range(2):
                state, _ = await open_card(offered)
                await save_food(Callback(), state)
            state, _ = await open_card(offered)
            await save(state)
            *_, meal = await meals(maker)

            async with maker() as session:
                day = (await session.execute(select(DayStat))).scalar_one()
                assert "meals" in day.quests_done.split(","), "проверять нечего"
                xp_before = day.xp

            press = Callback(f"food:undo:{meal.id}")
            await undo_saved(press)
            assert len(await meals(maker)) == 2
            assert "Запись отменена" in press.message.edited[-1]
            assert await events(maker, analytics.MEAL_UNDONE) == 1

            # Кристаллы за день пересчитаны по дневнику, в котором этой еды нет.
            async with maker() as session:
                day = (await session.execute(select(DayStat))).scalar_one()
                assert "meals" not in day.quests_done.split(","), \
                    "задание осталось закрытым едой, которой нет"
                assert day.xp < xp_before

            # Второе нажатие — не ошибка и не вторая отметка в учёте.
            again = Callback(f"food:undo:{meal.id}")
            await undo_saved(again)
            assert again.answers[-1] == "Этой записи уже нет"
            assert await events(maker, analytics.MEAL_UNDONE) == 1
    run(scenario)


def test_fix_changes_the_weight_of_the_saved_meal(offered):
    async def scenario():
        from handlers.food import apply_fix_saved, ask_fix_saved
        from states.food import FoodStates

        async with database() as maker:
            state, _ = await open_card(offered)
            await save(state)
            [meal] = await meals(maker)

            fix_state = State()
            await ask_fix_saved(Callback(f"food:fix:{meal.id}"), fix_state)
            assert fix_state.state == FoodStates.fixing_saved

            reply = Message()
            reply.text = "200"
            await apply_fix_saved(reply, fix_state)

            [fixed] = await meals(maker)
            assert fixed.id == meal.id, "исправление завело новую запись"
            assert fixed.weight_g == 200
            assert fixed.calories == pytest.approx(280)
            assert "Исправлено" in reply.said[-1]
            assert fix_state.state is None
    run(scenario)


def test_nobody_can_undo_or_fix_someone_elses_meal(offered):
    async def scenario():
        from handlers.food import ask_fix_saved, undo_saved

        async with database() as maker:
            state, _ = await open_card(offered)
            await save(state)
            [meal] = await meals(maker)

            stranger = Callback(f"food:undo:{meal.id}", user_id=555)
            await undo_saved(stranger)
            fix = Callback(f"food:fix:{meal.id}", user_id=555)
            fix_state = State()
            await ask_fix_saved(fix, fix_state)

            assert len(await meals(maker)) == 1
            assert fix_state.state is None
    run(scenario)


def test_an_old_meal_without_weight_can_only_be_undone():
    """Старые записи без веса: править нечего, отменить — можно."""
    async def scenario():
        from handlers.food import ask_fix_saved, undo_saved
        from models import MealSourceEnum, MealTypeEnum

        async with database() as maker:
            async with maker() as session:
                session.add(Meal(user_id=USER_ID, name="Старое", weight_g=None,
                                 calories=100, source=MealSourceEnum.TEXT,
                                 meal_type=MealTypeEnum.SNACK))
                await session.commit()
            [meal] = await meals(maker)

            fix_state = State()
            press = Callback(f"food:fix:{meal.id}")
            await ask_fix_saved(press, fix_state)
            assert fix_state.state is None
            assert "отменить" in press.answers[-1]

            await undo_saved(Callback(f"food:undo:{meal.id}"))
            assert await meals(maker) == []
    run(scenario)


def test_a_failed_save_keeps_the_card_and_says_so(offered, monkeypatch):
    """Не записалось — карточка возвращается, и человек знает, что делать."""
    async def scenario():
        import handlers.food as food

        async with database() as maker:
            state, _ = await open_card(offered)
            kept = dict(state.data)

            async def broken(*args, **kwargs):
                raise RuntimeError("база ушла")
            monkeypatch.setattr(food, "save_meal", broken)

            done = await save(state)
            assert await meals(maker) == []
            assert state.data == kept, "карточка потерялась вместе с записью"
            assert "ничего не попало" in done.message.said[-1]
    run(scenario)


def test_a_broken_summary_does_not_pretend_the_meal_was_lost(offered, monkeypatch):
    """Запись легла, а итоги упали: говорить «не записалось» нельзя —
    повторное «Сохранить» завело бы вторую запись."""
    async def scenario():
        import handlers.food as food

        async with database() as maker:
            state, _ = await open_card(offered)

            async def broken(*args, **kwargs):
                raise RuntimeError("игра упала")
            monkeypatch.setattr(food, "_sync_day", broken)

            done = await save(state)
            assert len(await meals(maker)) == 1
            assert state.data == {}
            assert "ничего не попало" not in " ".join(done.message.said)
            assert "Записал" in done.message.said[-1]
    run(scenario)


def test_two_fast_presses_on_save_after_an_offer_write_once(offered):
    async def scenario():
        from handlers.food import save_food

        async with database() as maker:
            state, _ = await open_card(offered)
            await asyncio.gather(save_food(Callback(), state), save_food(Callback(), state))
            assert len(await meals(maker)) == 1
    run(scenario)
