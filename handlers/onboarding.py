"""Пошаговый онбординг (FSM): анкета пользователя → расчёт нормы КБЖУ и воды."""

from __future__ import annotations

import logging
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
from keyboards.main_menu import main_menu_keyboard
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
from services import analytics, referrals, sources
from services.subscriptions import check_access, ensure_trial
from services.slides import send_slide
from services.video_notes import send_circle
from states.onboarding import OnboardingStates
from utils.formulas import ActivityLevel, Gender, Goal, calculate_macros, daily_water_ml
from utils.parsing import parse_float, parse_int

logger = logging.getLogger(__name__)
router = Router(name="onboarding")

GENDER_RU = {GenderEnum.MALE.value: "мужской", GenderEnum.FEMALE.value: "женский"}




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
            f"И ещё: ты пришла по ссылке подруги — держи {дни(to_newcomer)} "
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
            f"{имя} завела профиль по твоей ссылке — тебе {дни(to_inviter)} "
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


# Девять вопросов одним списком — и это единственное место, где они написаны.
# Раньше каждый вопрос жил внутри своего обработчика, и посчитать их было
# неоткуда: ни сказать человеку «третий из девяти», ни вернуть его туда, где
# он остановился. А главное — вторая копия вопроса рано или поздно разъехалась
# бы с первой, и человек, вернувшийся в анкету, увидел бы не тот вопрос, на
# котором стоит.
# Анкета кончается ровно там, где норму уже можно посчитать. Всё остальное
# спрашивается после — когда человек уже получил, ради чего отвечал.
#
# Что осталось: пол, возраст, рост и вес — из них считается основной обмен;
# активность и цель — из них суточная норма; тип питания — он один тап и
# решает, что человеку вообще предлагать (вегану мясо в первый же день —
# это видимая ошибка, которая дороже одного нажатия).
#
# Что ушло: целевой вес и аллергии. Ни то ни другое в норму не входит, зато
# оба спрашиваются текстом — а набирать труднее, чем нажимать. Из пяти
# печатаемых ответов осталось три.
ШАГИ: tuple[Шаг, ...] = (
    Шаг(OnboardingStates.gender, "Укажи свой пол:", gender_keyboard),
    Шаг(OnboardingStates.age, "Сколько тебе полных лет?"),
    Шаг(OnboardingStates.height, "Какой у тебя рост, см? Например: 172"),
    Шаг(OnboardingStates.current_weight, "Какой у тебя текущий вес, кг? Например: 68.5"),
    Шаг(OnboardingStates.activity_level, "Какой у тебя уровень активности?",
        activity_keyboard),
    Шаг(OnboardingStates.goal, "Какая у тебя цель?", goal_keyboard),
    Шаг(OnboardingStates.diet_type, "Тип питания:", diet_type_keyboard),
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
    await message.answer(текст, reply_markup=клавиатура)


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
        user.full_name = message.from_user.full_name
        if command.args and not user.referral:
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
            "таблица. Число шагов вносишь сама — смотри его в «Здоровье» "
            "на телефоне."
        )

    if completed:
        greeting = "С возвращением! 👋 Чем займёмся сегодня?"
        if config.PAYWALL and access.allowed and access.is_trial:
            greeting += f"\n\nПробный период: осталось {access.days_left} дн."
        await message.answer(greeting, reply_markup=main_menu_keyboard())
        return

    # Человек уже отвечал и вернулся. Раньше здесь стоял state.clear(), и
    # анкета начиналась с первого вопроса: пять честных ответов стирались
    # молча, а Telegram именно /start и подсовывает кнопкой. Второй раз
    # проходить то же самое не станет никто.
    шаг = ПО_СОСТОЯНИЮ.get(await state.get_state())
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
        f"Ты остановилась на вопросе {номер_шага(шаг)} из {ВСЕГО_ШАГОВ}. "
        f"Осталось {осталось} — это меньше минуты.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == CB_RESUME)
async def resume_onboarding(callback: CallbackQuery, state: FSMContext) -> None:
    """Продолжить с того вопроса, на котором стоим."""
    шаг = ПО_СОСТОЯНИЮ.get(await state.get_state())
    await callback.answer()
    if шаг is None:
        # Состояние успело протухнуть (через две недели строку убирают) —
        # продолжать нечего, но и молчать нельзя.
        await begin_onboarding(callback.message, state, callback.from_user.id)
        return
    await спросить(callback.message, шаг)


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

    await state.set_state(OnboardingStates.gender)
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


@router.callback_query(OnboardingStates.gender, F.data.startswith("onb_gender:"))
async def process_gender(callback: CallbackQuery, state: FSMContext) -> None:
    gender_value = callback.data.split(":", 1)[1]
    await state.update_data(gender=gender_value)
    await state.set_state(OnboardingStates.age)
    await callback.message.edit_text(f"Пол: {GENDER_RU[gender_value]} ✅")
    await спросить(callback.message, ПО_СОСТОЯНИЮ[OnboardingStates.age.state])
    await callback.answer()


@router.message(OnboardingStates.age, F.text)
async def process_age(message: Message, state: FSMContext) -> None:
    age = parse_int(message.text)
    if age is None or not (MIN_AGE <= age <= MAX_AGE):
        await message.answer(f"Введи возраст числом от {MIN_AGE} до {MAX_AGE}, например: 28")
        return
    await state.update_data(age=age)
    await state.set_state(OnboardingStates.height)
    await спросить(message, ПО_СОСТОЯНИЮ[OnboardingStates.height.state])


@router.message(OnboardingStates.height, F.text)
async def process_height(message: Message, state: FSMContext) -> None:
    height = parse_float(message.text)
    if height is None or not (MIN_HEIGHT_CM <= height <= MAX_HEIGHT_CM):
        await message.answer(
            f"Введи рост числом от {MIN_HEIGHT_CM:.0f} до {MAX_HEIGHT_CM:.0f} см, например: 172"
        )
        return
    await state.update_data(height_cm=height)
    await state.set_state(OnboardingStates.current_weight)
    await спросить(message, ПО_СОСТОЯНИЮ[OnboardingStates.current_weight.state])


@router.message(OnboardingStates.current_weight, F.text)
async def process_current_weight(message: Message, state: FSMContext) -> None:
    weight = parse_float(message.text)
    if weight is None or not (MIN_WEIGHT_KG <= weight <= MAX_WEIGHT_KG):
        await message.answer(
            f"Введи вес числом от {MIN_WEIGHT_KG:.0f} до {MAX_WEIGHT_KG:.0f} кг, например: 68.5"
        )
        return
    await state.update_data(current_weight_kg=weight)
    await state.set_state(OnboardingStates.activity_level)
    # Середина анкеты и конец печатания: дальше только кнопки. Слайд стоит
    # ровно здесь, на том же месте по счёту, что и раньше.
    await send_slide(message, "why_questions")
    await спросить(message, ПО_СОСТОЯНИЮ[OnboardingStates.activity_level.state])


@router.message(OnboardingStates.target_weight, F.text)
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
    await state.update_data(activity_level=activity_value)
    await state.set_state(OnboardingStates.goal)
    await callback.message.edit_text("Уровень активности сохранён ✅")
    await спросить(callback.message, ПО_СОСТОЯНИЮ[OnboardingStates.goal.state])
    await callback.answer()


@router.callback_query(OnboardingStates.goal, F.data.startswith("onb_goal:"))
async def process_goal(callback: CallbackQuery, state: FSMContext) -> None:
    goal_value = callback.data.split(":", 1)[1]
    await state.update_data(goal=goal_value)
    await state.set_state(OnboardingStates.diet_type)
    await callback.message.edit_text("Цель сохранена ✅")
    await спросить(callback.message, ПО_СОСТОЯНИЮ[OnboardingStates.diet_type.state])
    await callback.answer()


@router.callback_query(OnboardingStates.diet_type, F.data.startswith("onb_diet:"))
async def process_diet_type(callback: CallbackQuery, state: FSMContext) -> None:
    diet_value = callback.data.split(":", 1)[1]
    await state.update_data(diet_type=diet_value)
    await callback.message.edit_text("Тип питания сохранён ✅")
    await callback.answer()
    # Последний вопрос: дальше сразу норма. Человека сюда передаём его
    # самого, а не автора сообщения: у сообщения с кнопкой автор — бот, и
    # профиль записался бы боту.
    await _finish_onboarding(callback.message, state, callback.from_user)


@router.message(OnboardingStates.allergies, F.text)
async def process_allergies(message: Message, state: FSMContext) -> None:
    """Прежний последний шаг. Из анкеты убран, обработчик оставлен.

    По той же причине, что и целевой вес: в момент обновления кто-то стоит
    ровно здесь, и без обработчика его ответ утонул бы вместе с анкетой.
    """
    text = message.text.strip()
    allergies = None if text.lower() in {"нет", "-", "none", "no"} else text
    await state.update_data(allergies=allergies)
    await _finish_onboarding(message, state, message.from_user)


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
        "Считать и взвешивать ничего не надо — это моя работа."
    )


def first_step_text() -> str:
    """Одно действие, а не список возможностей."""
    return (
        "С чего начать прямо сейчас:\n\n"
        "📷 Сфотографируй то, что ешь или пьёшь — хоть кофе, хоть печенье. "
        "Я узнаю блюдо и посчитаю КБЖУ сама.\n\n"
        "Можно и словами: «два бутерброда с сыром».\n\n"
        "Остальное подождёт: шаги, вода, тренировки и подбор еды — на кнопках "
        "внизу. А всё красивое — кольца, мир и таблица команды — живёт в "
        "приложении."
    )


def open_app_keyboard() -> InlineKeyboardMarkup | None:
    """Кнопки под итогом анкеты: приложение и, необязательно, музыка.

    Музыка стоит здесь и больше нигде. Это единственное место, где у
    человека уже есть результат и появляется свободная минута; в меню и на
    экранах она была бы навязчивой, а «кнопка повсюду» — это не
    предложение, а реклама.

    Ничего не задерживает и ничем не управляет: обычная ссылка, без
    подписки, без автозапуска и без обещаний, что музыка на что-то влияет.
    Не открылась — остальное работает как работало.
    """
    builder = InlineKeyboardBuilder()
    сколько = 0

    if config.WEBAPP_URL:
        builder.button(text="📱 Открыть приложение",
                       web_app=WebAppInfo(url=config.WEBAPP_URL))
        сколько += 1
    if config.MUSIC_URL:
        builder.button(text=config.MUSIC_BUTTON, url=config.MUSIC_URL)
        сколько += 1

    # Пустая клавиатура — не то же самое, что её отсутствие: Telegram на неё
    # ругается. Раньше функция возвращала None без адреса приложения, и это
    # поведение обязано сохраниться.
    if not сколько:
        return None
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
        if user is None:
            user = User(id=кто.id)
            session.add(user)

        user.username = кто.username
        user.full_name = кто.full_name
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
        нужны_аллергии = not user.allergies

    await state.clear()
    await message.answer(
        norms_text(macros, water_ml),
        reply_markup=main_menu_keyboard(),
    )
    # Вторым сообщением — одно действие. Список возможностей в конце анкеты
    # человек не читает: он только что ответил на девять вопросов и ждёт,
    # что теперь. Ответ должен быть один и выполнимый прямо сейчас.
    await message.answer(first_step_text(), reply_markup=open_app_keyboard())
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
