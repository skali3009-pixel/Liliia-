"""FSM-состояния сценария добавления еды."""

from aiogram.fsm.state import State, StatesGroup


class FoodStates(StatesGroup):
    # Ждём фото или текстовое описание после кнопки «📷 Добавить еду».
    waiting_input = State()
    # Показана карточка распознавания, ждём действия по кнопкам.
    confirming = State()
    # Пользователь вводит правильное название блюда («не то блюдо»).
    correcting_dish = State()
    # Пользователь вводит вес порции в граммах.
    correcting_weight = State()
