"""Пошаговый онбординг (FSM): анкета пользователя → расчёт нормы КБЖУ и воды."""

from __future__ import annotations

import logging
from html import escape
from dataclasses import dataclass
from typing import Callable

import config
from services.step_sync import plural
from aiogram import F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import (CallbackQuery, InlineKeyboardMarkup, Message,
                           WebAppInfo)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db import get_session
from keyboards.main_menu import MENU_TEXTS, main_menu_keyboard
from keyboards.onboarding import (
    activity_keyboard,
    diet_type_keyboard,
    gender_keyboard,
    goal_keyboard,
)
from models import ActivityLevelEnum, DietTypeEnum, GenderEnum, GoalEnum, User
from handlers.legal import consent_keyboard, needs_consent, welcome_text
from services.profile import (
    MAX_AGE,
    MAX_HEIGHT_CM,
    MAX_WEIGHT_KG,
    MIN_AGE,
    MIN_HEIGHT_CM,
    MIN_WEIGHT_KG,
)
from services import analytics, music, referrals, sources
from services import age as age_rules
from services.age import ADULT_AGE
from services.subscriptions import check_access, ensure_trial
from services.slides import send_slide
from services.video_notes import send_circle
from states.onboarding import OnboardingStates
from utils.formulas import ActivityLevel, Gender, Goal, calculate_macros, daily_water_ml
from utils.parsing import parse_float, parse_int

logger = logging.getLogger(__name__)
router = Router(name="onboarding")

GENDER_RU = {GenderEnum.MALE.value: "мужской", GenderEnum.FEMALE.value: "женский"}

INTERESTS = {"food": "Питание", "move": "Тренировки", "both": "Питание и тренировки"}


def interest_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value, label in INTERESTS.items():
        builder.button(text=label, callback_data=f"onb_interest:{value}")
    builder.adjust(1)
    return builder.as_markup()


def name_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Оставить это имя", callback_data="onb_name:confirm")
    return builder.as_markup()


def allergies_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Нет аллергий и непереносимостей", callback_data="onb_allergies:none")
    return builder.as_markup()




async def _accept_invite(session, user_id: int, args: str | None) -> str | None:
    """Принять приглашение из ссылки. Возвращает имя друга или None."""
    from services import friends

    code = friends.code_from_args(args)
    if code is None:
        return None

    owner = await friends.owner_of(session, code)
    if owner is None or owner == user_id:
        return None

    result = await friends.connect(session, user_id, owner)
    if result not in {"ok", "already"}:
        return None

    friend = await session.get(User, owner)
    return (friend.full_name or "").split(" ")[0] if friend else "друг"


def дни(n: int) -> str:
    """«7 дней», «1 день» — число здесь всегда рядом со словом."""
    return f"{n} {plural(n, 'день', 'дня', 'дней')}"


async def _thank_for_invite(message: Message, кто, inviter_id: int,
                            to_inviter: int, to_newcomer: int) -> None:
    """Сказать обеим сторонам про начисленные дни.

    Приглашающей пишем в её собственный чат, а она бота могла и заблокировать:
    отправка в чужой чат обязана уметь не получиться. Уронить здесь анкету
    новенькой из-за чужой настройки приватности нельзя — она пришла заводить
    профиль, а не доставлять подруге сообщение.
    """
    if to_newcomer:
        await message.answer(
            f"И ещё: ты здесь по приглашению — держи {дни(to_newcomer)} "
            "доступа сверх обычного срока."
        )

    if not to_inviter or not inviter_id:
        return

    # Имя берём у человека, а не у автора сообщения: последний шаг анкеты —
    # кнопка, и автором там числится бот. Подруга получила бы «AURA завела
    # профиль по твоей ссылке».
    имя = (кто.full_name or "").split(" ")[0] or "Подруга"
    try:
        await message.bot.send_message(
            inviter_id,
            f"{имя} теперь в AURA по твоей ссылке — тебе {дни(to_inviter)} "
            "доступа в подарок. Спасибо!"
        )
    except Exception as error:  # noqa: BLE001 — чужой чат нам не подчиняется
        logger.warning("Не смогли поблагодарить %s за приглашение: %s",
                       inviter_id, error)


async def _accept_team(session, user_id: int, args: str | None) -> str | None:
    """Вступить в команду из ссылки. Возвращает её название или None."""
    from services import teams

    if not args or not args.startswith(teams.TEAM_PREFIX):
        return None

    status, team = await teams.join(session, user_id, args[len(teams.TEAM_PREFIX):])
    if status not in {"ok", "same"} or team is None:
        return None
    return team.name


@dataclass(frozen=True)
class Шаг:
    """Один вопрос анкеты: где стоим, что спрашиваем и чем отвечают."""

    состояние: State
    текст: str
    клавиатура: Callable[[], InlineKeyboardMarkup] | None = None


# Один список для счётчика, продолжения анкеты и напоминания.
# Имя и интерес нужны для первого действия; диета и аллергии — до подбора еды.
# Целевой вес остаётся необязательной настройкой после сохранения профиля.
ШАГИ: tuple[Шаг, ...] = (
    Шаг(OnboardingStates.interest, "Что тебе сейчас полезнее?", interest_keyboard),
    Шаг(OnboardingStates.name, "Как к тебе обращаться? Напиши имя или оставь предложенное.",
        name_keyboard),
    Шаг(OnboardingStates.gender, "Укажи свой пол:", gender_keyboard),
    Шаг(OnboardingStates.age, "Сколько тебе полных лет?"),
    Шаг(OnboardingStates.height, "Какой у тебя рост, см? Например: 172"),
    Шаг(OnboardingStates.current_weight, "Какой у тебя текущий вес, кг? Например: 68.5"),
    Шаг(OnboardingStates.activity_level, "Какой у тебя уровень активности?",
        activity_keyboard),
    Шаг(OnboardingStates.goal, "Какая у тебя цель?", goal_keyboard),
    Шаг(OnboardingStates.diet_type, "Тип питания:", diet_type_keyboard),
    Шаг(OnboardingStates.allergies,
        "Есть аллергии или непереносимости? Напиши продукты через запятую. "
        "Если их нет, нажми кнопку ниже.", allergies_keyboard),
)

ВСЕГО_ШАГОВ = len(ШАГИ)
ПО_СОСТОЯНИЮ = {шаг.состояние.state: шаг for шаг in ШАГИ}


def номер_шага(шаг: Шаг) -> int:
    """Который это вопрос по счёту, начиная с единицы."""
    return ШАГИ.index(шаг) + 1


async def спросить(message: Message, шаг: Шаг, *, вступление: str = "") -> None:
    """Задать вопрос, назвав его номер.

    «Вопрос 3 из 9» стоит здесь не для красоты. Девять вопросов подряд без
    счётчика — это дорога без конца: человек не знает, ответил он половину
    или десятую часть, и бросает ровно там, где кажется, что конца нет.
    Счётчик берётся из списка, а не пишется руками, — иначе однажды окажется
    «вопрос 7 из 9», а за ним ещё четыре.
    """
    шапка = f"Вопрос {номер_шага(шаг)} из {ВСЕГО_ШАГОВ}"
    текст = f"{вступление}{шапка}\n{шаг.текст}"
    клавиатура = шаг.клавиатура() if шаг.клавиатура else None
    await message.answer(текст, reply_markup=клавиатура, parse_mode="HTML")


def trial_line() -> str:
    """Строка про пробный период — или пустая, пока оплата выключена.

    Вынесена отдельно нарочно: раньше она собиралась прямо в обработчике, и
    тест проверял не её, а собственную копию тех же слов. Такой тест
    проходит и на сломанном коде.

    Пока бот бесплатен для всех, «первые дни бесплатно» — обещание платы,
    которой нет: человек ждёт, что его вот-вот отключат, и не вкладывается.

    А когда оплата включена, важно не «сколько дано», а «зачем столько».
    Срок здесь не щедрость: это время, за которое заводится привычка. Без
    второй фразы три недели читаются как «потом заплати», а не как
    «попробуй по-настоящему».
    """
    if not config.PAYWALL:
        return ""
    дней = config.TRIAL_DAYS
    return (f"Первые {дней} {plural(дней, 'день', 'дня', 'дней')} — бесплатно. "
            "Этого хватает, чтобы записывать еду и движение не «когда "
            "вспомнил», а каждый день.\n")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    """Первое знакомство: заводим человека, выдаём пробный период, ведём в анкету.

    Метка из ссылки (t.me/бот?start=МЕТКА) сохраняется, чтобы было видно,
    из какого поста или рекламы пришёл человек.
    """
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        # Правда ли строку заводим прямо сейчас. Ровно это отличает
        # «пришёл по ссылке» от «уже был и открыл бота ещё раз»: у второго
        # источник первого привлечения неизвестен, и выдавать за него
        # сегодняшнюю метку нельзя.
        новый = user is None
        if user is None:
            user = User(id=message.from_user.id)
            session.add(user)
            await session.flush()

        user.username = message.from_user.username
        # После подтверждения анкеты имя принадлежит профилю пользователя.
        if not user.onboarding_completed:
            user.full_name = message.from_user.full_name
        if command.args and command.args != "add_food" and not user.referral:
            user.referral = command.args[:64]
        # Источник — только из закрытого списка меток. Неизвестный параметр
        # обрабатывается штатно и в отчёт не попадает: произвольной строке
        # там не место.
        sources.apply(user, command.args, is_new=новый)
        # И сам факт обработанного запуска. Новый профиль и уже
        # существовавший считаются порознь — иначе «новые пользователи»
        # окажутся числом нажатий «Начать».
        await analytics.note(
            session, user.id, analytics.BOT_START,
            kind=analytics.NEW_PROFILE if новый else analytics.EXISTING_PROFILE,
            once="once_a_day")
        await session.commit()

        # Ссылка-приглашение от друга: t.me/бот?start=friend_КОД. Связь
        # создаётся сразу, потому что обе стороны уже согласились — один
        # прислал ссылку, второй по ней перешёл.
        joined = await _accept_invite(session, user.id, command.args)
        # Ссылка в команду: t.me/бот?start=team_КОД. Тоже сразу — тот, кто
        # перешёл по ссылке, уже согласился.
        team_name = await _accept_team(session, user.id, command.args)

        # И отдельной строкой — кто кого привёл. Дружбу разрывают, а эта
        # запись остаётся: по ней потом начисляют дни, и ссора двух подруг
        # не должна отменять заработанное. Пока оплата выключена, запись
        # только копится и ничего не выдаёт.
        await referrals.remember(session, user.id, command.args)

        # Пробный период отсчитывается от первого «Привет», а не от конца анкеты.
        await ensure_trial(session, user.id)
        access = await check_access(session, user.id)
        completed = user.onboarding_completed
        ask_consent = await needs_consent(user)

    # Пока человек не согласился с условиями, дальше не идём.
    if ask_consent:
        await state.clear()
        await message.answer(welcome_text(), reply_markup=consent_keyboard(),
                             disable_web_page_preview=True)
        return

    if joined:
        await message.answer(
            f"🤝 Теперь вы с {joined} друзья.\n\n"
            "Друг видит только игровое: кристаллы, уровень и серию. "
            "Вес, замеры, фотографии и дневник еды не видит никто, кроме тебя."
        )

    if team_name:
        await message.answer(
            f"👟 Ты в команде «{team_name}».\n\n"
            "Считаем шаги вместе: у команды общий счёт за неделю и своя "
            "таблица. Число шагов вносишь вручную — смотри его в «Здоровье» "
            "на телефоне."
        )

    if completed:
        if command.args == "add_food":
            from handlers.food import start_adding_food
            await start_adding_food(message, state)
            return
        greeting = "С возвращением! 👋 Чем займёмся сегодня?"
        if config.PAYWALL and access.allowed and access.is_trial:
            greeting += f"\n\nПробный период: осталось {access.days_left} дн."
        await message.answer(greeting, reply_markup=main_menu_keyboard())
        return

    # Человек уже отвечал и вернулся. Раньше здесь стоял state.clear(), и
    # анкета начиналась с первого вопроса: пять честных ответов стирались
    # молча, а Telegram именно /start и подсовывает кнопкой. Второй раз
    # проходить то же самое не станет никто.
    current = await state.get_state()
    if current == OnboardingStates.summary.state:
        await show_summary(message, state, message.from_user.id)
        return
    шаг = ПО_СОСТОЯНИЮ.get(current)
    if шаг is not None:
        await предложить_продолжить(message, шаг)
        return

    await state.clear()
    await begin_onboarding(message, state, message.from_user.id)


CB_RESUME = "onb:resume"
CB_RESTART = "onb:restart"


async def предложить_продолжить(message: Message, шаг: Шаг) -> None:
    """Вернулся в незаконченную анкету — спрашиваем, продолжить или заново."""
    осталось = ВСЕГО_ШАГОВ - номер_шага(шаг) + 1
    builder = InlineKeyboardBuilder()
    builder.button(text="Продолжить", callback_data=CB_RESUME)
    builder.button(text="Начать заново", callback_data=CB_RESTART)
    builder.adjust(1)
    await message.answer(
        f"Анкета ждёт тебя на вопросе {номер_шага(шаг)} из {ВСЕГО_ШАГОВ}. "
        f"Осталось {осталось} — это меньше минуты.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == CB_RESUME)
async def resume_onboarding(callback: CallbackQuery, state: FSMContext) -> None:
    """Продолжить с того вопроса, на котором стоим."""
    шаг = ПО_СОСТОЯНИЮ.get(await state.get_state())
    await callback.answer()
    if await state.get_state() == OnboardingStates.summary.state:
        await show_summary(callback.message, state, callback.from_user.id)
        return
    if шаг is None:
        # Состояние успело протухнуть (через две недели строку убирают) —
        # продолжать нечего, но и молчать нельзя.
        await begin_onboarding(callback.message, state, callback.from_user.id)
        return
    await ask_current(callback.message, state)


@router.callback_query(F.data == CB_RESTART)
async def restart_onboarding(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await begin_onboarding(callback.message, state, callback.from_user.id)


async def begin_onboarding(message: Message, state: FSMContext, user_id: int) -> None:
    """Начать анкету. Вызывается и из /start, и сразу после согласия."""
    async with get_session() as session:
        user = await session.get(User, user_id)
        completed = bool(user and user.onboarding_completed)

    if completed:
        await message.answer("С возвращением! 👋 Чем займёмся сегодня?",
                             reply_markup=main_menu_keyboard())
        return

    await state.update_data(interest="both", profile_name=(user.full_name or "").strip()[:80]
                            if user else "")
    await state.set_state(OnboardingStates.interest)
    # Начало анкеты — для воронки «начали / закончили» по людям.
    async with get_session() as session:
        if await session.get(User, user_id) is not None:
            await analytics.note(session, user_id, analytics.ONBOARDING_STARTED,
                                 once="once_ever")
            await session.commit()
    # Первая строка называет не только цену, но и награду. «Настроим профиль»
    # — это работа без обещания: человек видит, сколько с него спросят, и не
    # видит, что он получит. Норма калорий и воды приходит сразу после
    # девятого вопроса, считается по его росту, весу и цели — и это
    # единственное, что мы правда можем пообещать за анкету сегодня, пока
    # доступ бесплатен для всех и «подарить дни» нечего.
    вступление = (
        "Настроим профиль — это 1-2 минуты.\n"
        "В конце посчитаю твою норму: калории, белки, жиры, углеводы и воду — "
        "по твоему росту, весу и цели.\n"
        f"{trial_line()}\n"
    )
    await спросить(message, ШАГИ[0], вступление=вступление)


async def ask_current(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current == OnboardingStates.name.state:
        data = await state.get_data()
        await спросить(message, ПО_СОСТОЯНИЮ[current],
                      вступление=f"Предложенное имя: {escape(data.get('profile_name') or 'не указано')}\n\n")
    else:
        await спросить(message, ПО_СОСТОЯНИЮ[current])


async def advance(message: Message, state: FSMContext, next_state: State, user_id: int) -> None:
    if (await state.get_data()).get("editing_summary"):
        await state.update_data(editing_summary=False)
        await show_summary(message, state, user_id)
        return
    await state.set_state(next_state)
    await ask_current(message, state)


@router.callback_query(OnboardingStates.interest, F.data.startswith("onb_interest:"))
async def process_interest(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value not in INTERESTS:
        await callback.answer("Выбери вариант на кнопке.")
        return
    await state.update_data(interest=value)
    await callback.answer()
    await advance(callback.message, state, OnboardingStates.name, callback.from_user.id)


@router.callback_query(OnboardingStates.name, F.data == "onb_name:confirm")
async def confirm_name(callback: CallbackQuery, state: FSMContext) -> None:
    if not (await state.get_data()).get("profile_name"):
        await callback.answer("Напиши имя сообщением.")
        return
    await callback.answer()
    await advance(callback.message, state, OnboardingStates.gender, callback.from_user.id)


@router.message(OnboardingStates.name, F.text, ~F.text.in_(MENU_TEXTS), ~F.text.startswith("/"))
async def process_name(message: Message, state: FSMContext) -> None:
    text = " ".join(message.text.split())
    if not text or len(text) > 80 or any(ord(c) < 32 for c in message.text):
        await message.answer("Напиши имя от 1 до 80 символов, без переноса строки.")
        return
    await state.update_data(profile_name=text)
    await advance(message, state, OnboardingStates.gender, message.from_user.id)


@router.callback_query(OnboardingStates.gender, F.data.startswith("onb_gender:"))
async def process_gender(callback: CallbackQuery, state: FSMContext) -> None:
    gender_value = callback.data.split(":", 1)[1]
    if gender_value not in GENDER_RU:
        await callback.answer("Выбери вариант на кнопке.")
        return
    await state.update_data(gender=gender_value)
    await callback.message.edit_text(f"Пол: {GENDER_RU[gender_value]} ✅")
    await advance(callback.message, state, OnboardingStates.age, callback.from_user.id)
    await callback.answer()


@router.message(OnboardingStates.age, F.text, ~F.text.in_(MENU_TEXTS), ~F.text.startswith("/"))
async def process_age(message: Message, state: FSMContext) -> None:
    age = parse_int(message.text)
    if age is not None and 0 < age < ADULT_AGE:
        # Младше 18 — не «введи ещё раз», а честный отказ: иначе человек
        # просто напишет 18, и взрослая норма уйдёт подростку. Возраст
        # запоминаем, чтобы письмо «анкета ждёт» его не звало обратно.
        await state.clear()
        async with get_session() as session:
            user = await session.get(User, message.from_user.id)
            if user is not None:
                user.age = age
                await session.commit()
        await message.answer(age_rules.REFUSAL)
        return
    if age is None or not (MIN_AGE <= age <= MAX_AGE):
        await message.answer(f"Введи возраст числом от {MIN_AGE} до {MAX_AGE}, например: 28")
        return
    await state.update_data(age=age)
    await advance(message, state, OnboardingStates.height, message.from_user.id)


@router.message(OnboardingStates.height, F.text, ~F.text.in_(MENU_TEXTS), ~F.text.startswith("/"))
async def process_height(message: Message, state: FSMContext) -> None:
    height = parse_float(message.text)
    if height is None or not (MIN_HEIGHT_CM <= height <= MAX_HEIGHT_CM):
        await message.answer(
            f"Введи рост числом от {MIN_HEIGHT_CM:.0f} до {MAX_HEIGHT_CM:.0f} см, например: 172"
        )
        return
    await state.update_data(height_cm=height)
    await advance(message, state, OnboardingStates.current_weight, message.from_user.id)


@router.message(OnboardingStates.current_weight, F.text, ~F.text.in_(MENU_TEXTS), ~F.text.startswith("/"))
async def process_current_weight(message: Message, state: FSMContext) -> None:
    weight = parse_float(message.text)
    if weight is None or not (MIN_WEIGHT_KG <= weight <= MAX_WEIGHT_KG):
        await message.answer(
            f"Введи вес числом от {MIN_WEIGHT_KG:.0f} до {MAX_WEIGHT_KG:.0f} кг, например: 68.5"
        )
        return
    await state.update_data(current_weight_kg=weight)
    # Середина анкеты и конец печатания: дальше только кнопки. Слайд стоит
    # ровно здесь, на том же месте по счёту, что и раньше.
    if not (await state.get_data()).get("editing_summary"):
        await send_slide(message, "why_questions")
    await advance(message, state, OnboardingStates.activity_level, message.from_user.id)


@router.message(OnboardingStates.target_weight, F.text, ~F.text.in_(MENU_TEXTS), ~F.text.startswith("/"))
async def process_target_weight(message: Message, state: FSMContext) -> None:
    """Прежний шаг. Из анкеты он убран, но обработчик остаётся — и надолго.

    В базе живут незаконченные разговоры (две недели), и в момент обновления
    кто-то стоит ровно здесь. Убери обработчик — и человек, набравший свой
    целевой вес, не получит ответа ни от кого: сценарий его съест, а нового
    вопроса не будет. Поэтому ответ принимается и человек едет дальше по
    новой, короткой цепочке.
    """
    weight = parse_float(message.text)
    if weight is None or not (MIN_WEIGHT_KG <= weight <= MAX_WEIGHT_KG):
        await message.answer(
            f"Введи вес числом от {MIN_WEIGHT_KG:.0f} до {MAX_WEIGHT_KG:.0f} кг, например: 62"
        )
        return
    await state.update_data(target_weight_kg=weight)
    await state.set_state(OnboardingStates.activity_level)
    await спросить(message, ПО_СОСТОЯНИЮ[OnboardingStates.activity_level.state])


@router.callback_query(OnboardingStates.activity_level, F.data.startswith("onb_activity:"))
async def process_activity(callback: CallbackQuery, state: FSMContext) -> None:
    activity_value = callback.data.split(":", 1)[1]
    if activity_value not in {v.value for v in ActivityLevelEnum}:
        await callback.answer("Выбери вариант на кнопке.")
        return
    await state.update_data(activity_level=activity_value)
    await callback.message.edit_text("Уровень активности сохранён ✅")
    await advance(callback.message, state, OnboardingStates.goal, callback.from_user.id)
    await callback.answer()


@router.callback_query(OnboardingStates.goal, F.data.startswith("onb_goal:"))
async def process_goal(callback: CallbackQuery, state: FSMContext) -> None:
    goal_value = callback.data.split(":", 1)[1]
    if goal_value not in {v.value for v in GoalEnum}:
        await callback.answer("Выбери вариант на кнопке.")
        return
    await state.update_data(goal=goal_value)
    await callback.message.edit_text("Цель сохранена ✅")
    await advance(callback.message, state, OnboardingStates.diet_type, callback.from_user.id)
    await callback.answer()


@router.callback_query(OnboardingStates.diet_type, F.data.startswith("onb_diet:"))
async def process_diet_type(callback: CallbackQuery, state: FSMContext) -> None:
    diet_value = callback.data.split(":", 1)[1]
    if diet_value not in {v.value for v in DietTypeEnum}:
        await callback.answer("Выбери вариант на кнопке.")
        return
    await state.update_data(diet_type=diet_value)
    await callback.message.edit_text("Тип питания сохранён ✅")
    await callback.answer()
    await advance(callback.message, state, OnboardingStates.allergies, callback.from_user.id)


@router.message(OnboardingStates.allergies, F.text, ~F.text.in_(MENU_TEXTS), ~F.text.startswith("/"))
async def process_allergies(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text or len(text) > 200:
        await message.answer("Напиши продукты в пределах 200 символов или нажми «Нет аллергий и непереносимостей».")
        return
    allergies = None if text.lower() in {"нет", "-", "none", "no"} else text
    await state.update_data(allergies=allergies, editing_summary=False)
    await show_summary(message, state, message.from_user.id)


@router.callback_query(OnboardingStates.allergies, F.data == "onb_allergies:none")
async def no_allergies(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(allergies=None, editing_summary=False)
    await callback.answer()
    await show_summary(callback.message, state, callback.from_user.id)


SUMMARY_FIELDS = (
    ("interest", "Интерес", OnboardingStates.interest),
    ("profile_name", "Имя", OnboardingStates.name),
    ("gender", "Пол", OnboardingStates.gender),
    ("age", "Возраст", OnboardingStates.age),
    ("height_cm", "Рост", OnboardingStates.height),
    ("current_weight_kg", "Вес", OnboardingStates.current_weight),
    ("activity_level", "Активность", OnboardingStates.activity_level),
    ("goal", "Цель", OnboardingStates.goal),
    ("diet_type", "Питание", OnboardingStates.diet_type),
    ("allergies", "Аллергии", OnboardingStates.allergies),
)


async def show_summary(message: Message, state: FSMContext, user_id: int) -> None:
    from keyboards.onboarding import ACTIVITY_LABELS, DIET_LABELS, GOAL_LABELS

    data = await state.get_data()
    # Совместимость с анкетами, начатыми до добавления имени и интереса.
    if not data.get("profile_name"):
        async with get_session() as session:
            user = await session.get(User, user_id)
            name = (user.full_name or "") if user else ""
        await state.update_data(profile_name=name[:80], interest=data.get("interest", "both"))
        data = await state.get_data()
    for field, _, field_state in SUMMARY_FIELDS:
        if field not in data or field == "profile_name" and not data[field]:
            await state.update_data(editing_summary=False)
            await state.set_state(field_state)
            await ask_current(message, state)
            return
    values = {
        "interest": INTERESTS[data["interest"]], "profile_name": data["profile_name"],
        "gender": GENDER_RU[data["gender"]], "age": f"{data['age']} лет",
        "height_cm": f"{data['height_cm']:g} см", "current_weight_kg": f"{data['current_weight_kg']:g} кг",
        "activity_level": ACTIVITY_LABELS[ActivityLevel(data["activity_level"])],
        "goal": GOAL_LABELS[Goal(data["goal"])], "diet_type": DIET_LABELS[DietTypeEnum(data["diet_type"])],
        "allergies": data["allergies"] or "нет — по твоему ответу",
    }
    lines = ["Проверь ответы перед сохранением:\n"]
    builder = InlineKeyboardBuilder()
    builder.button(text="Всё верно — сохранить", callback_data="onb:confirm")
    for field, label, _ in SUMMARY_FIELDS:
        lines.append(f"{label}: {escape(str(values[field]))}")
    builder.button(text="Изменить ответы", callback_data="onb:edit_fields")
    builder.adjust(1)
    lines.append("\nДо подтверждения ответы остаются черновиком.")
    await state.set_state(OnboardingStates.summary)
    await message.answer("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(OnboardingStates.summary, F.data == "onb:edit_fields")
async def choose_edit_field(callback: CallbackQuery) -> None:
    builder = InlineKeyboardBuilder()
    for field, label, _ in SUMMARY_FIELDS:
        builder.button(text=label, callback_data=f"onb_edit:{field}")
    builder.adjust(2)
    builder.button(text="Назад к сводке", callback_data="onb:review")
    await callback.answer()
    await callback.message.answer("Что исправить?", reply_markup=builder.as_markup())


@router.callback_query(OnboardingStates.summary, F.data == "onb:review")
async def review_again(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await show_summary(callback.message, state, callback.from_user.id)


@router.callback_query(OnboardingStates.summary, F.data.startswith("onb_edit:"))
async def edit_summary(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.split(":", 1)[1]
    target = next((s for f, _, s in SUMMARY_FIELDS if f == field), None)
    if target is None:
        await callback.answer("Поле не найдено.")
        return
    await state.update_data(editing_summary=True)
    await state.set_state(target)
    await callback.answer()
    await ask_current(callback.message, state)


@router.callback_query(OnboardingStates.summary, F.data == "onb:confirm")
async def confirm_summary(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _finish_onboarding(callback.message, state, callback.from_user)


@router.callback_query(F.data == "onb:confirm")
async def stale_confirmation(callback: CallbackQuery) -> None:
    await callback.answer("Эта сводка уже закрыта. Для продолжения отправь /start.", show_alert=True)


def norms_text(macros, water_ml: int) -> str:
    """Норма — то, ради чего человек отвечал на девять вопросов."""
    return (
        "Профиль настроен! 🎉\n\n"
        "Твоя суточная норма:\n"
        f"🔥 Калории: {macros.calories} ккал\n"
        f"🥩 Белки: {macros.protein_g} г\n"
        f"🥑 Жиры: {macros.fat_g} г\n"
        f"🍚 Углеводы: {macros.carbs_g} г\n"
        f"🥦 Клетчатка: {macros.fiber_g} г\n"
        f"💧 Вода: {water_ml} мл\n\n"
        "Это ориентир, а не точное назначение. Калории по фото — оценка; "
        "порцию и состав можно поправить перед записью."
    )


def first_step_text(interest: str = "both") -> str:
    """Один следующий шаг — на выбор из двух, а не список возможностей.

    Решение 27.09: не доказано, что всем нужна именно запись еды, поэтому
    первым делом можно выбрать и еду, и движение. Оба — одно нажатие и
    результат сразу; второе не обязательно.
    """
    if interest == "move":
        return ("Начни с короткой тренировки: 5–15 минут дома, каждое движение показано.\n\n"
                "Нажми кнопку ниже. Питание, вода и прогресс останутся доступны в приложении.")
    if interest == "food":
        return ("Начни с одного приёма пищи: сфотографируй то, что ешь или пьёшь, "
                "или напиши словами: «два бутерброда с сыром».\n\n"
                "Калории — оценка. Проверь состав и порцию перед записью.")
    return (
        "С чего начать — выбери одно, второе подождёт:\n\n"
        "📷 Записать еду. Сфотографируй то, что ешь или пьёшь, или напиши "
        "словами: «два бутерброда с сыром». Калории — оценка: порцию можно "
        "поправить.\n\n"
        "🏃 Короткая тренировка. 5–15 минут дома, каждое движение показано.\n\n"
        "Остальное — вода, шаги, подбор еды — на кнопках внизу и в приложении."
    )


CB_FIRST_MEAL = "first:meal"
CB_FIRST_MOVE = "first:move"


def first_step_keyboard(interest: str = "both") -> InlineKeyboardMarkup:
    """Две кнопки выбора. Еда — прямо в чате; тренировка — на «Спорте»."""
    builder = InlineKeyboardBuilder()
    if interest != "move":
        builder.button(text="📷 Записать еду", callback_data=CB_FIRST_MEAL)
    if interest == "food":
        builder.adjust(1)
        return builder.as_markup()
    if config.WEBAPP_URL:
        base = config.WEBAPP_URL.rstrip("/")
        builder.button(text="🏃 Короткая тренировка",
                       web_app=WebAppInfo(url=f"{base}?screen=gym"))
    else:
        builder.button(text="🏃 Короткая тренировка", callback_data=CB_FIRST_MOVE)
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == CB_FIRST_MOVE)
async def first_move_without_app(callback: CallbackQuery) -> None:
    """Приложения нет — честно сказать, где тренировки, а не молчать."""
    await callback.answer()
    await callback.message.answer(
        "Тренировки с показом движений живут в приложении, а оно сейчас не "
        "подключено. Отметить своё занятие можно кнопкой «Тренировка» внизу.")


def open_app_keyboard() -> InlineKeyboardMarkup | None:
    """Кнопка приложения под итогом анкеты; музыка доступна в профиле и /music."""
    builder = InlineKeyboardBuilder()

    # Пустая клавиатура — не то же самое, что её отсутствие: Telegram на неё
    # ругается. Без адреса приложения функция возвращала None, и это
    # поведение обязано сохраниться.
    if not config.WEBAPP_URL:
        return None

    builder.button(text="📱 Открыть приложение",
                   web_app=WebAppInfo(url=config.WEBAPP_URL))
    builder.adjust(1)
    return builder.as_markup()


# Цели, при которых число на весах — финиш. У поддержания и рекомпозиции
# «цель по весу» смысла не имеет, и спрашивать её там незачем: тот же
# справочник, что и в services/goal.py, но импортировать его сюда ради двух
# значений — тянуть половину игрового слоя в анкету.
ЦЕЛИ_С_ВЕСОМ = (GoalEnum.LOSE_WEIGHT, GoalEnum.GAIN_MASS)


async def _offer_the_rest(message: Message, *, нужен_вес: bool,
                          нужны_аллергии: bool) -> None:
    """Предложить то, что убрано из анкеты. После нормы, не до неё.

    Целевой вес и аллергии в норму не входят, и держать их перед человеком
    значит брать плату вперёд за то, чего он ещё не видел. Здесь всё иначе:
    норма уже посчитана, предложение ничего не загораживает, а не ответить
    на него ничего не стоит — поэтому и кнопки «потом» нет. Кнопка, которая
    ничего не меняет, учит, что бота можно не слушать.

    Спрашиваем только то, чего правда нет и что правда нужно: цель по весу —
    лишь там, где число на весах вообще финиш.
    """
    from keyboards.profile import CB_EDIT

    строки, builder = [], InlineKeyboardBuilder()

    if нужен_вес:
        строки.append("• цель по весу — тогда на «Прогрессе» появится линия, "
                      "к которой идём")
        builder.button(text="🎯 Цель по весу", callback_data=f"{CB_EDIT}target_weight")

    if нужны_аллергии:
        строки.append("• аллергии и непереносимости — чтобы не предлагать тебе "
                      "того, что нельзя")
        builder.button(text="🚫 Аллергии", callback_data=f"{CB_EDIT}allergies")

    if not строки:
        return

    builder.adjust(1)
    шапка = ("Ещё пара необязательных штрихов — норма от них не меняется:"
             if len(строки) > 1 else
             "Ещё одна необязательная мелочь — норма от неё не меняется:")
    await message.answer(
        шапка + "\n\n" + "\n".join(строки) +
        "\n\nМожно сейчас, можно когда угодно потом — в профиле.",
        reply_markup=builder.as_markup(),
    )


async def _finish_onboarding(message: Message, state: FSMContext, кто) -> None:
    """Посчитать норму и записать профиль.

    `кто` передаётся отдельно от `message` нарочно. Последний шаг анкеты —
    кнопка, а у сообщения с кнопкой автор бот, не человек: возьми мы автора
    из сообщения, профиль записался бы боту, а человек остался бы без
    анкеты навсегда — и молча.
    """
    data = await state.get_data()
    if any(field not in data for field, _, _ in SUMMARY_FIELDS):
        await show_summary(message, state, кто.id)
        return

    macros = calculate_macros(
        gender=Gender(data["gender"]),
        weight_kg=data["current_weight_kg"],
        height_cm=data["height_cm"],
        age_years=data["age"],
        activity_level=ActivityLevel(data["activity_level"]),
        goal=Goal(data["goal"]),
    )
    water_ml = daily_water_ml(
        weight_kg=data["current_weight_kg"],
        height_cm=data["height_cm"],
        activity_level=ActivityLevel(data["activity_level"]),
    )

    async with get_session() as session:
        user = await session.get(User, кто.id)
        if user is not None and user.onboarding_completed:
            await state.clear()
            await message.answer("Профиль уже сохранён. Продолжим?", reply_markup=main_menu_keyboard())
            return
        if user is None:
            user = User(id=кто.id)
            session.add(user)

        user.username = кто.username
        user.full_name = data.get("profile_name") or кто.full_name
        user.onboarding_interest = data.get("interest", "both")
        user.gender = GenderEnum(data["gender"])
        user.age = data["age"]
        user.height_cm = data["height_cm"]
        user.current_weight_kg = data["current_weight_kg"]
        user.target_weight_kg = data.get("target_weight_kg")
        user.activity_level = ActivityLevelEnum(data["activity_level"])
        user.goal = GoalEnum(data["goal"])
        user.diet_type = DietTypeEnum(data["diet_type"])
        user.allergies = data.get("allergies")
        user.daily_calories = macros.calories
        user.daily_protein_g = macros.protein_g
        user.daily_fat_g = macros.fat_g
        user.daily_carbs_g = macros.carbs_g
        user.daily_fiber_g = macros.fiber_g
        user.daily_water_ml = water_ml
        user.onboarding_completed = True

        await session.commit()

        # Анкета дошла до конца — значит, пришёл человек, а не нажатие.
        # Наградой это становится только при включённой оплате; иначе
        # обе строки вернут нули и никто ничего не получит.
        пригласила, ей_дней, мне_дней = await referrals.reward_signup(session, user.id)

        # Раз в жизни: `onboarding_completed` поднимается однажды, и второго
        # завершения у одного человека не бывает. Повторная доставка того же
        # события счётчик не двигает.
        await analytics.note(session, user.id, analytics.PROFILE_COMPLETED,
                             once="once_ever")
        await session.commit()

        # Чего человеку ещё не хватает — считаем здесь, пока сессия открыта.
        # Снаружи это обращение к отсоединённому объекту: сегодня оно живо
        # только потому, что сессии заведены с expire_on_commit=False, а это
        # настройка в другом файле и не наше обещание.
        нужен_вес = not user.target_weight_kg and user.goal in ЦЕЛИ_С_ВЕСОМ
        нужны_аллергии = "allergies" not in data

    await state.clear()
    await message.answer(
        norms_text(macros, water_ml),
        reply_markup=main_menu_keyboard(),
    )
    # Вторым сообщением — одно действие. Список возможностей в конце анкеты
    # человек не читает: он только что ответил на девять вопросов и ждёт,
    # что теперь. Ответ должен быть один и выполнимый прямо сейчас.
    # И кружком — то же самое голосом. Последним, а не первым: кнопка
    # «Открыть приложение» должна остаться под большим пальцем.
    await send_circle(message, "ready")
    # И последним — что приложение не единственный вход. Команды лежат за
    # синей кнопкой, куда никто не смотрит, а открывать приложение готовы
    # не все: без этой картинки половина бота для них не существует.
    await send_slide(message, "in_chat_too")

    # И самым последним — подарок за приглашение, если он есть. Последним
    # нарочно: человек только что получил одно понятное действие, и
    # заслонять его хорошей новостью значит менять дело на настроение.
    await _thank_for_invite(message, кто, пригласила, ей_дней, мне_дней)

    # И только теперь — то, что убрали из анкеты. Человек уже получил норму
    # и одно понятное действие; отсюда любой его ответ добровольный.
    await _offer_the_rest(message, нужен_вес=нужен_вес,
                          нужны_аллергии=нужны_аллергии)

    # Самой последней — карточка второго проекта Лилии. Последней нарочно:
    # всё, что придёт после, уводит её выше экрана, а прошлый раз она
    # именно так и пропадала. Ничем не управляет и ничего не задерживает:
    # не отправилась — анкета всё равно закончена (`services/music.py`).
    # The first useful action must remain the last message on the screen.
    # Music stays available through /music and the Profile tab.
    interest = data.get("interest", "both")
    await message.answer(first_step_text(interest), reply_markup=first_step_keyboard(interest))
