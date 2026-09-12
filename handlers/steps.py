"""Шаги из чата.

Приложение шаги не считает: доступа ни к «Здоровью» на айфоне, ни к датчику
у мини-приложения внутри Telegram нет. Число вносит человек — и тому, кто
живёт в переписке, а приложение не открывает, нужен для этого путь в чате.
Иначе он просто выпадает из всей затеи с командой и рейтингом.

Считается всё тем же кодом, что и в приложении (services/steps.py): цель,
серия, задание дня и награды одни и те же, откуда бы ни пришло число.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from db import get_session
from keyboards.main_menu import MENU_STEPS, MENU_TEXTS, main_menu_keyboard
from models import User
from services import step_sync
from services import steps as step_service
from services import turn as turn_service
from services.checkins import today_state
from services.gamification import sync_today
from services.meals import get_today_totals, list_today_meals
from services.water import today_total_ml
from states.steps import StepStates
from utils.plural import plural

logger = logging.getLogger(__name__)
router = Router(name="steps")

ASK = (
    "👟 Сколько шагов сегодня?\n\n"
    "Число смотри в «Здоровье» на телефоне — я его сам не вижу. "
    "Напиши цифрой, например: 8500.\n\n"
    "Чтобы больше не вбивать руками — /sync: телефон будет присылать шаги "
    "сам, по расписанию.\n\n"
    "Передумала — нажми любую кнопку меню."
)

NOT_A_NUMBER = (
    "Это не похоже на число шагов. Напиши просто цифрой: 8500."
)

NOT_READY = "Сначала настроим профиль — напиши /start."


def render(walk: step_service.Steps, game: dict | None = None) -> str:
    """Что человек видит после ввода. Те же цифры, что и на кольце."""
    lines = [f"👟 Записал: {walk.today} шагов из {walk.goal}"]
    lines.append("Норма пройдена 👏" if walk.done
                 else f"Осталось {walk.left} — это примерно "
                      f"{max(round(walk.left / 100), 1)} минут пешком.")
    if walk.streak:
        # Отдельно от общей серии в игровых строчках: это разные счётчики,
        # и два одинаковых «🔥 дней подряд» в одном сообщении путают.
        days = plural(walk.streak, "день", "дня", "дней")
        lines.append(f"🔥 {walk.streak} {days} подряд с нормой шагов")
    lines.append(f"На этой неделе {walk.week}")
    lines += turn_service.game_lines(game or {})
    return "\n".join(lines)


async def _save(message: Message, raw: str) -> bool:
    """Записать число и ответить. False — если это вообще не число."""
    value = step_service.clean_steps(raw)
    if value is None:
        return False

    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None or not user.onboarding_completed:
            await message.answer(NOT_READY)
            return True

        tz = user.timezone
        await step_service.record(session, user.id, value, timezone_name=tz)
        walk = await step_service.state(session, user, timezone_name=tz)

        # Игровой итог считаем здесь же: шаги могли закрыть задание дня, и
        # узнать об этом приятнее сразу, а не при следующем входе.
        state = await today_state(session, user.id, timezone_name=tz)
        game = await sync_today(
            session, user,
            meals_count=len(await list_today_meals(session, user.id, timezone_name=tz)),
            calories=(await get_today_totals(session, user.id, timezone_name=tz)).calories,
            fiber_g=(await get_today_totals(session, user.id, timezone_name=tz)).fiber_g,
            water_ml=await today_total_ml(session, user.id, timezone_name=tz),
            timezone_name=tz, stress_marked=state.stress is not None,
        )

    await message.answer(render(walk, game), reply_markup=main_menu_keyboard())
    return True


# Кнопка меню важнее недописанного ответа: иначе человек, ушедший отсюда в
# «Воду», остался бы в ожидании числа.
@router.message(StateFilter(StepStates), F.text.in_(MENU_TEXTS))
async def leave_waiting(message: Message, state: FSMContext) -> None:
    await state.clear()
    raise SkipHandler


@router.message(F.text == MENU_STEPS)
async def ask_steps(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None or not user.onboarding_completed:
            await message.answer(NOT_READY)
            return
        walk = await step_service.state(session, user, timezone_name=user.timezone)

    await state.set_state(StepStates.waiting_number)
    known = (f"\n\nСейчас записано {walk.today} из {walk.goal}. "
             "Новое число заменит его, а не прибавится."
             if walk.today else "")
    await message.answer(ASK + known)


@router.message(Command("steps"))
async def steps_command(message: Message, state: FSMContext,
                        command: CommandObject) -> None:
    """`/steps 8500` — записать сразу, `/steps` — спросить число."""
    if command.args and await _save(message, command.args):
        await state.clear()
        return
    await ask_steps(message, state)


@router.message(Command("sync"))
async def show_sync(message: Message, state: FSMContext) -> None:
    """Как сделать, чтобы шаги приходили сами.

    Вбивать число каждый день не будет почти никто, и тогда всё, что стоит
    на шагах, не работает. Читать «Здоровье» из Telegram нельзя, но телефон
    умеет присылать шаги сам — этому и учит инструкция.
    """
    await state.clear()
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None or not user.onboarding_completed:
            await message.answer(NOT_READY)
            return
        token = await step_service.sync_token(session, user)
        synced = await step_service.last_sync(session, user.id)

    text = step_sync.instructions(step_sync.link_for(token))
    if synced:
        text += f"\n\nПоследняя присылка с телефона: {synced:%d.%m в %H:%M}."
    await message.answer(text, disable_web_page_preview=True,
                         reply_markup=main_menu_keyboard())


@router.message(StepStates.waiting_number, F.text)
async def take_number(message: Message, state: FSMContext) -> None:
    if not await _save(message, message.text):
        # Состояние не сбрасываем: человек ошибся, а не передумал.
        await message.answer(NOT_A_NUMBER)
        return
    await state.clear()
