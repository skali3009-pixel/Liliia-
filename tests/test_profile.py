"""Тесты правки профиля после анкеты (services/profile.py + карточка в боте)."""

import asyncio
import contextlib

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from handlers.profile import CHOICE_FIELDS, TEXT_FIELDS, profile_text
from keyboards.onboarding import activity_keyboard, diet_type_keyboard, goal_keyboard
from keyboards.profile import CB_BACK, FIELD_LABELS, edit_menu_keyboard, with_back
from models import (ActivityLevelEnum, Base, DietTypeEnum, GenderEnum, GoalEnum, User)
from services import profile as svc
from services.progress import add_measurement


@contextlib.asynccontextmanager
async def db(**overrides):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        fields = dict(
            id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165.0,
            current_weight_kg=70.0, target_weight_kg=62.0,
            activity_level=ActivityLevelEnum.LIGHT, goal=GoalEnum.LOSE_WEIGHT,
            diet_type=DietTypeEnum.REGULAR, onboarding_completed=True,
        )
        fields.update(overrides)
        user = User(**fields)
        svc.recalculate(user)
        session.add(user)
        await session.commit()
        yield session, user
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def test_changing_the_goal_recalculates_the_norm():
    """Иначе человек ставит набор массы и продолжает есть по дефициту."""
    async def scenario():
        async with db() as (session, user):
            before = user.daily_calories
            assert await svc.set_goal(session, user, "gain_mass") is True
            assert user.goal is GoalEnum.GAIN_MASS
            assert user.daily_calories > before
    run(scenario)


def test_changing_activity_recalculates_the_norm():
    async def scenario():
        async with db() as (session, user):
            before = user.daily_calories
            assert await svc.set_activity(session, user, "very_high") is True
            assert user.daily_calories > before
            assert user.daily_water_ml
    run(scenario)


def test_changing_age_and_height_recalculates_the_norm():
    async def scenario():
        async with db() as (session, user):
            before = user.daily_calories
            assert await svc.set_height(session, user, 180.0) is True
            assert user.daily_calories != before
            assert await svc.set_age(session, user, 55) is True
    run(scenario)


def test_diet_does_not_touch_the_norm():
    """Тип питания меняет подбор блюд, а не калораж — цифры трогать нельзя."""
    async def scenario():
        async with db() as (session, user):
            before = (user.daily_calories, user.daily_protein_g)
            assert await svc.set_diet(session, user, "vegan") is False
            assert user.diet_type is DietTypeEnum.VEGAN
            assert (user.daily_calories, user.daily_protein_g) == before
    run(scenario)


@pytest.mark.parametrize("text", ["нет", "НЕТ", "-", "   ", "никаких"])
def test_no_allergies_is_stored_as_empty(text):
    """Строка «нет» в промпте подбора выглядела бы как аллергия на слово «нет»."""
    async def scenario():
        async with db(allergies="орехи") as (session, user):
            await svc.set_allergies(session, user, text)
            assert user.allergies is None
    run(scenario)


def test_allergies_are_saved():
    async def scenario():
        async with db() as (session, user):
            await svc.set_allergies(session, user, "  орехи, лактоза  ")
            assert user.allergies == "орехи, лактоза"
    run(scenario)


def test_target_weight_is_saved_without_touching_the_norm():
    async def scenario():
        async with db() as (session, user):
            before = user.daily_calories
            await svc.set_target_weight(session, user, 58.0)
            assert user.target_weight_kg == 58.0
            assert user.daily_calories == before
    run(scenario)


@pytest.mark.parametrize("value,ok", [(62.0, True), (30.0, True), (300.0, True),
                                      (29.9, False), (300.1, False), (None, False)])
def test_target_weight_limits(value, ok):
    assert svc.valid_target(value) is ok


@pytest.mark.parametrize("value,ok", [(28, True), (10, True), (100, True),
                                      (9, False), (101, False), (None, False)])
def test_age_limits(value, ok):
    assert svc.valid_age(value) is ok


@pytest.mark.parametrize("value,ok", [(172.0, True), (100.0, True), (250.0, True),
                                      (99.0, False), (251.0, False), (None, False)])
def test_height_limits(value, ok):
    assert svc.valid_height(value) is ok


def test_incomplete_profile_keeps_its_old_numbers():
    """Пересчёт без данных не должен обнулять норму, которая уже была."""
    async def scenario():
        async with db() as (session, user):
            before = user.daily_calories
            user.age = None
            assert svc.recalculate(user) is False
            assert user.daily_calories == before
    run(scenario)


def test_weighing_in_and_editing_the_profile_agree_on_the_numbers():
    """Две двери к одной формуле: разъедутся — человек увидит разные нормы."""
    async def scenario():
        async with db() as (session, user):
            measured, updated = await add_measurement(session, user=user, weight_kg=64.0)
            assert updated is True
            after_weighing = user.daily_calories

            user.current_weight_kg = 70.0
            svc.recalculate(user)
            assert user.daily_calories != after_weighing

            user.current_weight_kg = 64.0
            svc.recalculate(user)
            assert user.daily_calories == after_weighing
            assert measured.weight_kg == 64.0
    run(scenario)


def test_every_button_on_the_card_leads_somewhere():
    """Кнопка без обработчика молча ничего не делает — это худший вид поломки."""
    assert set(FIELD_LABELS) == set(TEXT_FIELDS) | set(CHOICE_FIELDS)


def test_card_buttons_are_wired_to_the_edit_prefix():
    codes = [b.callback_data for row in edit_menu_keyboard().inline_keyboard for b in row]
    assert len(codes) == len(FIELD_LABELS)
    assert all(code.startswith("prof_edit:") for code in codes)


@pytest.mark.parametrize("keyboard", [goal_keyboard, activity_keyboard, diet_type_keyboard])
def test_profile_and_onboarding_do_not_share_callbacks(keyboard):
    """Один и тот же выбор не должен срабатывать в чужом сценарии."""
    onboarding = [b.callback_data for row in keyboard().inline_keyboard for b in row]
    editing = [b.callback_data for row in keyboard(prefix="prof").inline_keyboard for b in row]
    assert all(code.startswith("onb_") for code in onboarding)
    assert all(code.startswith("prof_") for code in editing)
    assert not set(onboarding) & set(editing)


@pytest.mark.parametrize("keyboard", [goal_keyboard, activity_keyboard, diet_type_keyboard])
def test_there_is_always_a_way_back(keyboard):
    rows = with_back(keyboard(prefix="prof")).inline_keyboard
    assert rows[-1][0].callback_data == CB_BACK
    assert len(rows) == len(keyboard(prefix="prof").inline_keyboard) + 1


def test_card_shows_the_whole_profile():
    async def scenario():
        async with db(allergies="орехи") as (_, user):
            text = profile_text(user)
            for part in ("похудение", "лёгкая", "обычное", "орехи", "165 см",
                         "70.0 кг → цель 62.0 кг", "ккал"):
                assert part in text
    run(scenario)


def test_card_survives_a_half_filled_profile():
    """Профиль из старой версии базы не должен ронять экран прочерками."""
    user = User(id=2, onboarding_completed=True)
    text = profile_text(user)
    assert "—" in text
    assert "Аллергии: нет" in text


# --- Проверка самих обработчиков: кнопка нажата — что-то произошло ---


class FakeMessage:
    """Минимальное сообщение: помнит, что ответили и чем перерисовали."""

    def __init__(self, user_id=1, text=""):
        self.from_user = type("U", (), {"id": user_id})()
        self.text = text
        self.answers: list[tuple[str, object]] = []
        self.edits: list[tuple[str, object]] = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data, message, user_id=1):
        self.data = data
        self.message = message
        self.from_user = type("U", (), {"id": user_id})()
        self.answers: list[str | None] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


class FakeState:
    def __init__(self):
        self.state = None

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        self.state = None

    async def get_state(self):
        return self.state


def bind(monkeypatch, session):
    """Подменяем сессию базы на тестовую — обработчик ходит в неё."""
    import handlers.profile as module

    @contextlib.asynccontextmanager
    async def fake_session():
        yield session

    monkeypatch.setattr(module, "get_session", fake_session)
    return module


def test_choosing_a_goal_from_the_card_saves_it_and_redraws(monkeypatch):
    async def scenario():
        async with db() as (session, user):
            module = bind(monkeypatch, session)
            message = FakeMessage()
            callback = FakeCallback("prof_goal:gain_mass", message)
            before = user.daily_calories

            await module.choose_goal(callback)

            assert user.goal is GoalEnum.GAIN_MASS
            assert user.daily_calories > before
            assert message.edits and "набор массы" in message.edits[-1][0]
            assert callback.answers == ["Норма пересчитана"]
    run(scenario)


def test_choosing_a_diet_reports_a_plain_save(monkeypatch):
    async def scenario():
        async with db() as (session, user):
            module = bind(monkeypatch, session)
            callback = FakeCallback("prof_diet:vegan", FakeMessage())
            await module.choose_diet(callback)
            assert callback.answers == ["Сохранено"]
    run(scenario)


def test_open_field_asks_a_question_for_text_fields(monkeypatch):
    async def scenario():
        async with db() as (session, _):
            module = bind(monkeypatch, session)
            message = FakeMessage()
            callback = FakeCallback("prof_edit:age", message)
            state = FakeState()

            await module.open_field(callback, state)

            assert await state.get_state() is module.ProfileStates.age
            assert "лет" in message.edits[-1][0]
    run(scenario)


def test_open_field_offers_options_for_choice_fields(monkeypatch):
    async def scenario():
        async with db() as (session, _):
            module = bind(monkeypatch, session)
            message = FakeMessage()
            await module.open_field(FakeCallback("prof_edit:goal", message), FakeState())

            text, markup = message.edits[-1]
            codes = [b.callback_data for row in markup.inline_keyboard for b in row]
            assert "prof_goal:lose_weight" in codes
            assert CB_BACK in codes
    run(scenario)


def test_wrong_number_does_not_get_saved(monkeypatch):
    """Возраст 300 — это опечатка, а не повод пересчитать норму."""
    async def scenario():
        async with db() as (session, user):
            module = bind(monkeypatch, session)
            state = FakeState()
            await state.set_state(module.ProfileStates.age)
            message = FakeMessage(text="300")

            await module.save_age(message, state)

            assert user.age == 30
            assert "от 10 до 100" in message.answers[-1][0]
            assert await state.get_state() is module.ProfileStates.age
    run(scenario)


def test_correct_number_is_saved_and_the_card_comes_back(monkeypatch):
    async def scenario():
        async with db() as (session, user):
            module = bind(monkeypatch, session)
            state = FakeState()
            await state.set_state(module.ProfileStates.target_weight)

            await module.save_target_weight(FakeMessage(text="58,5"), state)

            assert user.target_weight_kg == 58.5
            assert await state.get_state() is None
    run(scenario)


def test_cancel_returns_to_the_card_without_changes(monkeypatch):
    """Из вопроса всегда должен быть выход, иначе бот держит человека в поле."""
    async def scenario():
        async with db(allergies="орехи") as (session, user):
            module = bind(monkeypatch, session)
            state = FakeState()
            await state.set_state(module.ProfileStates.allergies)
            message = FakeMessage(text="отмена")

            await module.save_allergies(message, state)

            assert user.allergies == "орехи"
            assert await state.get_state() is None
            assert message.answers and "Твой профиль" in message.answers[-1][0]
    run(scenario)


def test_menu_button_cancels_editing():
    """Ушёл из вопроса в другую кнопку — следующая фраза не должна попасть в анкету."""
    async def scenario():
        import handlers.profile as module
        from aiogram.dispatcher.event.bases import SkipHandler

        state = FakeState()
        await state.set_state(module.ProfileStates.height)
        with pytest.raises(SkipHandler):
            await module.leave_editing(FakeMessage(text="💧 Вода"), state)
        assert await state.get_state() is None
    run(scenario)


def test_guard_knows_every_menu_button():
    """Новая кнопка меню без этой проверки снова начнёт ловить чужой ответ."""
    from keyboards.main_menu import main_menu_keyboard
    from handlers.profile import MENU_TEXTS

    buttons = {b.text for row in main_menu_keyboard().keyboard for b in row}
    assert buttons == MENU_TEXTS
