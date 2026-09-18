"""FSM-состояние ввода шагов.

Одно: человек называет число. Отдельная группа, а не общая с едой, — иначе
«9200» посреди добавления блюда уехало бы в распознавание как название.
"""

from aiogram.fsm.state import State, StatesGroup


class StepStates(StatesGroup):
    waiting_number = State()
