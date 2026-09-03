"""FSM-состояния сценария онбординга."""

from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    gender = State()
    age = State()
    height = State()
    current_weight = State()
    target_weight = State()
    activity_level = State()
    goal = State()
    diet_type = State()
    allergies = State()
