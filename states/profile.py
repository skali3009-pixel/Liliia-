"""FSM-состояния правки профиля.

Отдельная группа, а не переиспользование OnboardingStates: анкета ведёт
человека по всем шагам подряд, а здесь он меняет ровно одно поле и
возвращается к карточке профиля.
"""

from aiogram.fsm.state import State, StatesGroup


class ProfileStates(StatesGroup):
    # Ждём текст: вес цели, рост, возраст, список аллергий.
    target_weight = State()
    height = State()
    age = State()
    allergies = State()
