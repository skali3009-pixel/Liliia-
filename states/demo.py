"""Состояния бесплатной примерки еды."""

from aiogram.fsm.state import State, StatesGroup


class DemoStates(StatesGroup):
    waiting_food = State()
