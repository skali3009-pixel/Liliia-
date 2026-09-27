"""Добавление еды: фото → Claude vision → карточка с КБЖУ → ручная коррекция → сохранение."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from db import get_session
from keyboards.food import (
    CB_CANCEL,
    CB_FIX,
    CB_LESS,
    CB_MORE,
    CB_SAVE,
    CB_UNDO,
    CB_WEIGHT,
    CB_WRONG_DISH,
    food_card_keyboard,
    saved_keyboard,
)
from keyboards.main_menu import MENU_ADD_MEAL, MENU_TEXTS
from models import Meal, MealSourceEnum, User
from services.food_vision import (
    CONFIDENCE_RU,
    FoodAnalysis,
    FoodNotRecognized,
    FoodRecognitionError,
    VisionNotConfigured,
    analyze_photo,
    analyze_text,
)
from services import alerts
from services.checkins import save_checkin, today_state
from services.gamification import sync_today
from services import turn as turn_service
from services.meals import (
    delete_meal, get_today_totals, list_today_meals, rescale_meal, save_meal,
)
from services.moments import Moment, analyze_moment, mood_word
from services.transcription import TranscriptionError, VoiceNotConfigured, transcribe
from services.water import today_total_ml
from services import usage
from utils.disk import usage as disk_usage
from states.food import FoodStates
from states.onboarding import OnboardingStates
from utils.meal_time import MEAL_TYPE_RU, guess_meal_type
from utils.parsing import parse_float
from utils.portions import MAX_WEIGHT_G, MIN_WEIGHT_G, adjust_weight, scale_nutrition
from utils.progress import format_remaining, render_progress_bar
from utils.timeframe import DEFAULT_TIMEZONE, get_zone

logger = logging.getLogger(__name__)
router = Router(name="food")

# Claude принимает изображения до 5 МБ; фото из Telegram обычно сильно меньше,
# но подстрахуемся понятным сообщением вместо ошибки API.
MAX_IMAGE_BYTES = 4_500_000

GENERIC_ERROR = (
    "Не получилось распознать блюдо — попробуй ещё раз или опиши его текстом.\n"
    "Например: «тарелка борща со сметаной и два куска бородинского»."
)


def _num(value: float) -> str:
    """Числа в карточке — без дробей: точность оценки этого не оправдывает."""
    return f"{round(value):g}"


# Совет даём там, где он нужен, — после неудачи. Показывать его каждому
# заранее бессмысленно: инструкцию читают, только когда что-то не вышло,
# а до этого она лишь удлиняет первое сообщение.
PHOTO_TIPS = (
    "\n\nЧтобы вышло с первого раза:\n"
    "• снимай сверху, всю тарелку целиком\n"
    "• при обычном свете, без вспышки в упор\n"
    "• одно блюдо в кадре — если их несколько, лучше по очереди\n"
    "• рядом что-то знакомое по размеру: вилка, стакан\n\n"
    "И всегда можно просто словами: «тарелка борща и два куска хлеба»."
)

# Когда модель сама сомневается, человеку надо сказать, что делать. Иначе
# он либо поверит неточной цифре, либо не запишет ничего.
LOW_CONFIDENCE_HINT = (
    "Похоже не очень уверенно. Если не сходится — «✏️ не то блюдо» "
    "или «⚖️ вес», пересчитаю."
)


def _render_card(analysis: FoodAnalysis, meal_type_label: str) -> str:
    confidence = CONFIDENCE_RU.get(analysis.confidence, analysis.confidence)
    lines = [
        f"🍽 {analysis.name}",
        f"⚖️ ~{_num(analysis.weight_g)} г · {meal_type_label}",
        "",
        # «≈», а не голое число: калории здесь всегда оценка — по фото, по
        # словам или по справочнику для порции, которую никто не взвешивал.
        f"🔥 ≈ {_num(analysis.calories)} ккал",
        f"🥩 Б {_num(analysis.protein_g)} · 🥑 Ж {_num(analysis.fat_g)} · "
        f"🍚 У {_num(analysis.carbs_g)} г",
        f"🥦 Клетчатка {_num(analysis.fiber_g)} г",
    ]
    if analysis.comment:
        lines += ["", f"💬 {analysis.comment}"]
    lines += [f"Уверенность: {confidence}"]
    if analysis.confidence == "low":
        lines += ["", LOW_CONFIDENCE_HINT]
    return "\n".join(lines)


def _current_meal_label(timezone_name: str = DEFAULT_TIMEZONE) -> str:
    """Завтрак/обед/ужин определяем по местному времени пользователя."""
    return MEAL_TYPE_RU[guess_meal_type(datetime.now(get_zone(timezone_name)))]


async def _show_card(
    message: Message, state: FSMContext, analysis: FoodAnalysis, *, photo_file_id: str | None,
    from_offer: bool = False,
) -> None:
    """Показать карточку распознавания и запомнить её для последующих правок.

    Через неё же идёт и блюдо из подбора (`from_offer`): предложенное — не
    съеденное, и записывать его одним нажатием значило выдавать порцию из
    справочника за ту, что лежала на тарелке. Карточка одна на всё: второй
    путь записи разошёлся бы с первым в правке порции и защите от двойного
    нажатия.
    """
    card = await message.answer(
        _render_card(analysis, _current_meal_label()), reply_markup=food_card_keyboard()
    )
    # Попытка записи — отдельно от записи: разница между ними и есть то, где
    # человек передумал или не поверил цифре. Сбой учёта карточку не ломает.
    try:
        from services import analytics

        async with get_session() as session:
            await analytics.note(session, message.chat.id, analytics.MEAL_ATTEMPT,
                                 once="once_a_day")
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Не отметилась попытка записи еды", exc_info=True)
    await state.set_state(FoodStates.confirming)
    await state.update_data(
        analysis=analysis.to_dict(),
        photo_file_id=photo_file_id,
        card_message_id=card.message_id,
        from_offer=from_offer,
    )


async def _update_card(message: Message, state: FSMContext, analysis: FoodAnalysis) -> None:
    """Перерисовать существующую карточку после коррекции."""
    data = await state.get_data()
    card_message_id = data.get("card_message_id")
    await state.update_data(analysis=analysis.to_dict())

    if card_message_id is None:
        await _show_card(message, state, analysis, photo_file_id=data.get("photo_file_id"))
        return

    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=card_message_id,
            text=_render_card(analysis, _current_meal_label()),
            reply_markup=food_card_keyboard(),
        )
    except TelegramBadRequest as e:
        # Текст не изменился (например, модель дала тот же результат) — не ошибка.
        if "message is not modified" not in str(e):
            raise


async def _ensure_onboarded(message: Message) -> User | None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)

    if user is None or not user.onboarding_completed:
        await message.answer(
            "Сначала настроим профиль — без него не посчитать остаток по норме. Напиши /start."
        )
        return None
    return user


# Кнопка меню важнее недописанного ответа — то же правило, что в шагах,
# жалобах и профиле. Без него нажатие уезжало в разбор еды: человек нажимал
# «Добавить еду», передумывал, жал «Воду» — и слово «💧 Вода» уходило в
# модель как описание блюда. Ошибка тихая: ни сообщения, ни отказа, просто
# ответ не про то, и потраченные на это деньги.
#
# Проверено перебором зарегистрированных обработчиков: в состоянии
# `FoodStates.waiting_input` нажатие любой кнопки меню, кроме «Добавить
# еду», доставалось `handle_food_text`.
@router.message(StateFilter(FoodStates), F.text.in_(MENU_TEXTS))
async def leave_food_input(message: Message, state: FSMContext) -> None:
    await state.clear()
    raise SkipHandler


FOOD_PROMPT = (
    "Пришли фото блюда 📷 — распознаю и посчитаю КБЖУ.\n"
    "Или расскажи словами — голосовым 🎤 или текстом: «на завтрак омлет "
    "из трёх яиц, чувствую себя бодрее». Запишу и еду, и самочувствие.\n\n"
    "Посмотреть, что уже записано за сегодня, — /day"
)


@router.message(F.text == MENU_ADD_MEAL)
async def start_adding_food(message: Message, state: FSMContext) -> None:
    if await _ensure_onboarded(message) is None:
        return

    await state.set_state(FoodStates.waiting_input)
    await message.answer(FOOD_PROMPT)


@router.callback_query(F.data == "first:meal")
async def first_meal_choice(callback: CallbackQuery, state: FSMContext) -> None:
    """Первый шаг после анкеты — «Записать еду»: то же, что кнопка меню."""
    await callback.answer()
    await state.set_state(FoodStates.waiting_input)
    await callback.message.answer(FOOD_PROMPT)


# Одно и то же фото люди пересылают чаще, чем кажется: не расслышал бот с
# первого раза, отправила подруге и себе, вернулась к старому сообщению.
# Второй раз платить за него незачем. Память живёт до перезапуска бота —
# отдельная таблица ради этого не нужна.
_recent_photos: OrderedDict[str, FoodAnalysis] = OrderedDict()
_RECENT_LIMIT = 500


def _remember_photo(key: str, analysis: FoodAnalysis) -> None:
    _recent_photos[key] = analysis
    _recent_photos.move_to_end(key)
    while len(_recent_photos) > _RECENT_LIMIT:
        _recent_photos.popitem(last=False)


async def _photo_allowed(message: Message, user_id: int) -> bool:
    """Можно ли сейчас распознавать фото: диск, дневной бюджет, лимит человека."""
    disk = disk_usage()
    if disk.full:
        await message.answer(
            "Сейчас не могу принять фото — на сервере кончается место. "
            "Запиши блюдо словами, это работает и считается так же точно."
        )
        logger.warning("Диск заполнен на %s%% — приём фото остановлен", disk.percent)
        return False

    async with get_session() as session:
        if await usage.over_budget(session):
            await message.answer(
                "Распознавание фото сегодня недоступно — исчерпан дневной лимит "
                "на обработку. Опиши блюдо словами: посчитаю так же точно."
            )
            # Люди упираются в потолок раньше, чем владелец узнаёт о нём из
            # утреннего отчёта. Сообщаем сразу; повторов не будет.
            spend = await usage.spent_today(session)
            await _warn_owner(
                message, alerts.BUDGET, "over",
                f"🛑 Дневной потолок исчерпан: {spend.total_usd:.2f} $ из "
                f"{config.DAILY_COST_LIMIT_USD:.0f} $.\n\n"
                "Распознавание фото и голоса до полуночи отключено — дневник, "
                "тренировки и всё остальное работают.\n\n"
                "Поднять потолок: `bash set-limit.sh <сумма>`",
            )
            return False

        left = await usage.photo_limit_left(session, user_id)

    if left <= 0:
        await message.answer(
            f"На сегодня распознавание фото исчерпано — это "
            f"{config.PHOTO_LIMIT_PER_DAY} снимков в сутки. Записывай словами: "
            "«тарелка борща и два куска хлеба» — я посчитаю."
        )
        return False
    return True


@router.message(~StateFilter(OnboardingStates), F.photo)
async def handle_food_photo(message: Message, state: FSMContext) -> None:
    """Фото — это всегда еда, в каком бы разговоре человек ни находился.

    Раньше сюда попадало только фото, присланное вне сценариев. Стоило
    человеку нажать «Шаги» и не ввести число, начать править рост в профиле
    или открыть «что-то не так» — и следующее фото не обрабатывал никто.
    Ни ответа, ни ошибки: бот просто молчал, а человек делал вывод, что
    сначала надо нажать «Добавить еду». Так и было: кнопка сбрасывала
    незаконченный сценарий, и фото наконец доходило.

    Исключение одно — анкета: там фото не еда, а сбитый набор ответов.
    """
    if await _ensure_onboarded(message) is None:
        return

    # Незаконченный чужой сценарий фото отменяет: человек занят другим.
    current = await state.get_state()
    if current is not None and not str(current).startswith("FoodStates"):
        await state.clear()

    photo = message.photo[-1]  # последний размер — самый крупный
    if photo.file_size and photo.file_size > MAX_IMAGE_BYTES:
        await message.answer("Фото слишком большое. Пришли его как фото (не файлом).")
        return

    known = _recent_photos.get(photo.file_unique_id)
    if known is not None:
        # То же самое фото уже разбирали — показываем результат без запроса.
        _recent_photos.move_to_end(photo.file_unique_id)
        await _show_card(message, state, known, photo_file_id=photo.file_id)
        return

    if not await _photo_allowed(message, message.from_user.id):
        return

    status = await message.answer("🔍 Распознаю блюдо…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    spent: list = []
    try:
        buffer = await message.bot.download(photo.file_id)
        if buffer is None:
            raise FoodRecognitionError("Не удалось скачать фото из Telegram")
        analysis = await analyze_photo(buffer.read(), on_usage=spent.append)
    except FoodNotRecognized as e:
        # Единственный случай, который человек может исправить сам, — и
        # только здесь совет уместен. При поломке ключа или сети он
        # бесполезен и выглядит издевательством.
        await status.edit_text(f"{e}{PHOTO_TIPS}")
        return
    except FoodRecognitionError as e:  # нет ключа, сеть, лимит у модели
        await status.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка распознавания фото еды")
        await status.edit_text(GENERIC_ERROR)
        await _report_failures(message)
        return

    finally:
        await _record_spend(message.from_user.id, "photo", spent)

    _remember_photo(photo.file_unique_id, analysis)
    await status.delete()
    await _show_card(message, state, analysis, photo_file_id=photo.file_id)


async def _warn_owner(message: Message, key: str, state: str, text: str) -> None:
    """Предупредить владельца, не задев человека.

    Сигнал — дело служебное. Если его не удалось отправить, человек всё
    равно должен получить свой ответ, а не ошибку.
    """
    try:
        await alerts.fire(message.bot, key, state, text)
    except Exception:  # noqa: BLE001
        logger.warning("Не удалось предупредить владельца: %s", key)


async def _report_failures(message: Message) -> None:
    """Сказать владельцу, если сбои пошли чередой.

    Сторож снаружи такого не увидит: процесс жив и отвечает, а люди вместо
    ответа получают извинение. Один сбой — не повод, череда — повод.
    """
    if not alerts.record_failure():
        return
    await _warn_owner(
        message, alerts.ERRORS, "many",
        f"⚠️ Подряд {alerts.failures_in_window()} сбоев распознавания за "
        f"{alerts.ERROR_WINDOW.seconds // 60} минут. Бот работает, но люди "
        "вместо ответа видят ошибку.\n\n"
        "Посмотреть, что случилось:\n"
        "`journalctl -u nutrition-bot -n 50`",
    )


async def _record_spend(user_id: int, kind: str, spent: list) -> None:
    """Записать расход. Ошибка учёта не должна мешать человеку есть."""
    if not spent:
        return
    try:
        async with get_session() as session:
            for item in spent:
                await usage.record(session, user_id=user_id, kind=kind,
                                   model=config.VISION_MODEL, usage=item)
    except Exception:  # noqa: BLE001
        logger.exception("Не записался расход на распознавание")


@router.message(~StateFilter(OnboardingStates), F.voice)
async def handle_food_voice(message: Message, state: FSMContext) -> None:
    """Голосовое сообщение: расшифровываем и считаем КБЖУ по тексту.

    Как и фото, работает в любом разговоре, кроме анкеты: голосовое — это
    всегда рассказ о еде, а не ответ на «сколько шагов».
    """
    if await _ensure_onboarded(message) is None:
        return

    current = await state.get_state()
    if current is not None and not str(current).startswith("FoodStates"):
        await state.clear()

    status = await message.answer("🎤 Слушаю…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        buffer = await message.bot.download(message.voice.file_id)
        if buffer is None:
            raise TranscriptionError("Не удалось скачать голосовое из Telegram")
        spoken = await transcribe(buffer.read())
    except (VoiceNotConfigured, TranscriptionError) as e:
        await status.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка расшифровки голосового сообщения")
        await status.edit_text("Не получилось разобрать голосовое. Попробуй ещё раз или напиши текстом.")
        return

    await status.edit_text(f"🎤 Услышал: {spoken}\n\n🔍 Разбираю…")

    try:
        moment = await analyze_moment(spoken, now=datetime.now(get_zone(DEFAULT_TIMEZONE)))
    except FoodRecognitionError as e:  # включая «нет ключа» и «не видно еды»
        await status.edit_text(f"🎤 Услышал: {spoken}\n\n{e}")
        return
    except Exception:
        logger.exception("Ошибка разбора голосового сообщения")
        await status.edit_text(GENERIC_ERROR)
        return

    await _handle_moment(message, state, moment, status)


@router.message(FoodStates.waiting_input, F.text, ~F.text.in_(MENU_TEXTS))
async def handle_food_text(message: Message, state: FSMContext) -> None:
    status = await message.answer("🔍 Разбираю…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        moment = await analyze_moment(message.text, now=datetime.now(get_zone(DEFAULT_TIMEZONE)))
    except FoodRecognitionError as e:  # включая «нет ключа» и «не видно еды»
        await status.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка разбора сообщения")
        await status.edit_text(GENERIC_ERROR)
        return

    await _handle_moment(message, state, moment, status)


def _render_state_line(moment: Moment) -> str:
    """Что записали из самочувствия — одной строкой."""
    parts = []
    if moment.energy:
        parts.append(f"⚡ энергия {moment.energy}/10")
    if moment.focus:
        parts.append(f"🎯 фокус {moment.focus}/10")
    if moment.mood:
        parts.append(f"🤍 настроение: {mood_word(moment.mood)}")
    if moment.stress:
        parts.append(f"〰️ стресс {moment.stress}")
    if moment.sleep_minutes:
        hours, minutes = divmod(moment.sleep_minutes, 60)
        parts.append(f"🌙 сон {hours} ч {minutes:02d} м")
    return ", ".join(parts)


async def _handle_moment(message: Message, state: FSMContext, moment: Moment, status) -> None:
    """Самочувствие записываем сразу, еду — через карточку с коррекцией."""
    saved_state = ""
    if moment.has_state:
        async with get_session() as session:
            await save_checkin(
                session,
                user_id=message.from_user.id,
                energy=moment.energy,
                focus=moment.focus,
                mood=moment.mood,
                stress=moment.stress,
                sleep_minutes=moment.sleep_minutes,
                note=moment.text,
            )
        saved_state = _render_state_line(moment)

    if moment.food is None:
        await status.edit_text(
            f"✅ Записала: {saved_state}" if saved_state
            else "Не нашла здесь ни еды, ни самочувствия. Скажи чуть подробнее."
        )
        return

    await status.delete()
    if saved_state:
        await message.answer(f"✅ Записала: {saved_state}")
    await _show_card(message, state, moment.food, photo_file_id=None)


async def _load_analysis(state: FSMContext) -> FoodAnalysis | None:
    data = await state.get_data()
    raw = data.get("analysis")
    return FoodAnalysis.from_dict(raw) if raw else None


def _rescaled(analysis: FoodAnalysis, new_weight_g: float) -> FoodAnalysis:
    scaled = scale_nutrition(
        {
            "calories": analysis.calories,
            "protein_g": analysis.protein_g,
            "fat_g": analysis.fat_g,
            "carbs_g": analysis.carbs_g,
            "fiber_g": analysis.fiber_g,
        },
        from_weight_g=analysis.weight_g,
        to_weight_g=new_weight_g,
    )
    return FoodAnalysis(
        name=analysis.name,
        weight_g=new_weight_g,
        calories=scaled["calories"],
        protein_g=scaled["protein_g"],
        fat_g=scaled["fat_g"],
        carbs_g=scaled["carbs_g"],
        fiber_g=scaled["fiber_g"],
        confidence=analysis.confidence,
        comment=analysis.comment,
    )


@router.callback_query(FoodStates.confirming, F.data.in_({CB_LESS, CB_MORE}))
async def change_portion(callback: CallbackQuery, state: FSMContext) -> None:
    analysis = await _load_analysis(state)
    if analysis is None:
        await callback.answer("Карточка устарела, пришли фото заново", show_alert=True)
        return

    new_weight = adjust_weight(analysis.weight_g, bigger=callback.data == CB_MORE)
    if new_weight == analysis.weight_g:
        await callback.answer("Дальше менять некуда")
        return

    await _update_card(callback.message, state, _rescaled(analysis, new_weight))
    await callback.answer()


@router.callback_query(FoodStates.confirming, F.data == CB_WEIGHT)
async def ask_weight(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FoodStates.correcting_weight)
    await callback.message.answer("Сколько граммов в порции? Например: 320")
    await callback.answer()


@router.message(FoodStates.correcting_weight, F.text, ~F.text.in_(MENU_TEXTS))
async def apply_weight(message: Message, state: FSMContext) -> None:
    weight = parse_float(message.text)
    if weight is None or not (MIN_WEIGHT_G <= weight <= MAX_WEIGHT_G):
        await message.answer(
            f"Введи вес числом от {MIN_WEIGHT_G:.0f} до {MAX_WEIGHT_G:.0f} г, например: 320"
        )
        return

    analysis = await _load_analysis(state)
    if analysis is None:
        await state.clear()
        await message.answer("Карточка устарела — пришли фото заново.")
        return

    await state.set_state(FoodStates.confirming)
    await _update_card(message, state, _rescaled(analysis, weight))


@router.callback_query(FoodStates.confirming, F.data == CB_WRONG_DISH)
async def ask_correct_dish(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FoodStates.correcting_dish)
    await callback.message.answer("Что это за блюдо? Напиши название — пересчитаю.")
    await callback.answer()


@router.message(FoodStates.correcting_dish, F.text, ~F.text.in_(MENU_TEXTS))
async def apply_correct_dish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    hint = message.text.strip()

    status = await message.answer("🔍 Пересчитываю…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    spent: list = []
    try:
        if photo_file_id:
            # Фото анализируем заново с подсказкой пользователя: название берём
            # из подсказки, а вес порции модель по-прежнему оценивает по фото.
            buffer = await message.bot.download(photo_file_id)
            if buffer is None:
                raise FoodRecognitionError("Не удалось скачать фото из Telegram")
            analysis = await analyze_photo(buffer.read(), hint=hint, on_usage=spent.append)
        else:
            analysis = await analyze_text(hint, on_usage=spent.append)
    except FoodRecognitionError as e:  # включая «нет ключа» и «не видно еды»
        await status.edit_text(str(e))
        return
    except Exception:
        logger.exception("Ошибка пересчёта блюда по уточнению пользователя")
        await status.edit_text(GENERIC_ERROR)
        return
    finally:
        await _record_spend(message.from_user.id, "photo" if photo_file_id else "text", spent)

    await status.delete()
    await state.set_state(FoodStates.confirming)
    await _update_card(message, state, analysis)


@router.callback_query(FoodStates.confirming, F.data == CB_SAVE)
async def save_food(callback: CallbackQuery, state: FSMContext) -> None:
    # Отвечаем Telegram сразу, до всякой работы с базой. Иначе кнопка
    # крутится всё время, пока считаются итоги дня и игровой пересчёт, а
    # через десять секунд Telegram перестаёт ждать — и снаружи это
    # выглядит как «нажала, и ничего не произошло».
    await callback.answer("Записываю…")

    analysis = await _load_analysis(state)
    if analysis is None:
        await state.clear()
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "Не могу найти эту карточку — похоже, она из прошлой версии бота.\n"
            "Пришли фото ещё раз, я посчитаю заново."
        )
        return

    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    from_offer = bool(data.get("from_offer"))

    # Пока считаются итоги, человек может нажать «Сохранить» ещё раз —
    # кнопка ведь на месте. Забываем карточку сразу: второе нажатие
    # запишет то же блюдо второй раз.
    await state.set_data({})

    try:
        saved = await _save_and_sum(callback, analysis, photo_file_id, from_offer)
    except Exception:
        # Карточку забыли до записи — от двойного нажатия. Не записалось —
        # значит, её надо вернуть: иначе человек остаётся с кнопкой, которая
        # отвечает «карточка устарела», и с едой, которой нет в дневнике.
        logger.exception("Не сохранилась запись еды")
        await state.set_data(data)
        await callback.message.answer(
            "Не получилось записать — в дневник ничего не попало. "
            "Нажми «✅ Сохранить» ещё раз через минуту."
        )
        return
    if saved is None:
        return
    meal_id, meal_type, totals, norms, game, cheetah, first = saved

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    # Под итогом — «Исправить вес» и «Отменить». Нижнее меню от этого не
    # пропадает: обычная клавиатура держится, пока её не убрали явно.
    await callback.message.answer(
        _render_day_summary(analysis, MEAL_TYPE_RU[meal_type], totals, norms, game,
                            cheetah=cheetah) + (FIRST_MEAL_NOTE if first else ""),
        reply_markup=saved_keyboard(meal_id),
    )


# После самой первой записи: что дальше — одной строкой и без обещаний.
FIRST_MEAL_NOTE = (
    "\n\n🌱 Первая запись есть. Дальше так же: фото или пара слов, когда ешь. "
    "Порция была другая — «Исправить вес» ниже."
)


async def _save_and_sum(callback: CallbackQuery, analysis: FoodAnalysis,
                        photo_file_id: str | None, from_offer: bool):
    async with get_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user is None or not user.onboarding_completed:
            await callback.message.answer("Сначала настрой профиль: /start")
            return None

        # Приём пищи — по местному времени человека, а не по часам сервера:
        # иначе вечерний перекус в Новосибирске записывался бы обедом.
        meal_type = guess_meal_type(datetime.now(get_zone(user.timezone or DEFAULT_TIMEZONE)))
        meal = await save_meal(
            session,
            user_id=user.id,
            analysis=analysis,
            # Снимок нужен был только на время распознавания: в дневнике от
            # него не остаётся следа, но по нему видно, откуда взялась запись.
            source=MealSourceEnum.PHOTO if photo_file_id else MealSourceEnum.TEXT,
            meal_type=meal_type,
            from_offer=from_offer,
        )
        norms = (
            user.daily_calories,
            user.daily_protein_g,
            user.daily_fat_g,
            user.daily_carbs_g,
            user.daily_fiber_g,
        )
        zone, owner, meal_id = user.timezone or DEFAULT_TIMEZONE, user.id, meal.id
        # Первая запись в жизни — повод сказать, что дальше, одной строкой.
        from sqlalchemy import func, select

        first = (await session.execute(
            select(func.count()).select_from(Meal).where(Meal.user_id == owner)
        )).scalar_one() == 1
        # Запись уже в базе. Всё, что ниже, — итоги и игра: их сбой не
        # повод говорить «не записалось» и возвращать карточку — повторное
        # «Сохранить» завело бы вторую запись. Итоги тогда просто короче.
        try:
            totals, game, day_state, water_ml = await _sync_day(session, user)
            # Гепард отзывается и в чате — тем же правилом, что и в приложении.
            # Совет здесь не даём: он живёт под кнопкой «Мой ход», а показанный
            # без спроса тратит дневной лимит повторов на подсказку, которую
            # человек сейчас не просил.
            cheetah = await turn_service.cheetah_for(
                session, user, user.timezone or DEFAULT_TIMEZONE,
                game=game, state=day_state, water=water_ml)
        except Exception:
            logger.exception("Запись еды сохранена, а итоги дня не посчитались")
            # После отката поля пользователя сброшены, и чтение их в async
            # упало бы — поэтому номер и пояс взяты заранее.
            await session.rollback()
            totals = await get_today_totals(session, owner, timezone_name=zone)
            game = cheetah = None
    return meal_id, meal_type, totals, norms, game, cheetah, first


async def _sync_day(session, user: User):
    """Итоги дня и игровой пересчёт после любой перемены в дневнике.

    Запись, отмена и правка веса идут через одно место: задание дня, которое
    закрыла запись, обязано открыться обратно, когда запись отменили, — иначе
    кристаллы за день остались бы за еду, которой в дневнике нет.
    """
    tz = user.timezone or DEFAULT_TIMEZONE
    totals = await get_today_totals(session, user.id, timezone_name=tz)
    day_state = await today_state(session, user.id, timezone_name=tz)
    water_ml = await today_total_ml(session, user.id, timezone_name=tz)
    game = await sync_today(
        session,
        user,
        meals_count=len(await list_today_meals(session, user.id, timezone_name=tz)),
        calories=totals.calories,
        fiber_g=totals.fiber_g,
        water_ml=water_ml,
        timezone_name=tz,
        stress_marked=day_state.stress is not None,
    )
    return totals, game, day_state, water_ml


async def _own_meal(session, callback: CallbackQuery, prefix: str) -> Meal | None:
    """Запись по кнопке — только своя: номер в кнопке подделать нетрудно."""
    try:
        meal_id = int(callback.data.removeprefix(prefix))
    except ValueError:
        return None
    meal = await session.get(Meal, meal_id)
    if meal is None or meal.user_id != callback.from_user.id:
        return None
    return meal


@router.callback_query(F.data.startswith(CB_UNDO))
async def undo_saved(callback: CallbackQuery) -> None:
    """«Отменить запись» под итогом. Состояние разговора не нужно: номер в кнопке."""
    async with get_session() as session:
        meal = await _own_meal(session, callback, CB_UNDO)
        if meal is None:
            # Второе нажатие, или запись уже убрана из /day или приложения.
            await callback.answer("Этой записи уже нет")
            await callback.message.edit_reply_markup(reply_markup=None)
            return
        name = meal.name
        user = await session.get(User, callback.from_user.id)
        await delete_meal(session, meal)
        totals, *_ = await _sync_day(session, user)
        norm = user.daily_calories

    await callback.answer("Запись отменена")
    await callback.message.edit_text(
        f"↩️ Запись отменена: {name}\n\n"
        f"🔥 Сегодня {_num(totals.calories)}" + (f" / {norm} ккал" if norm else " ккал")
    )


@router.callback_query(F.data.startswith(CB_FIX))
async def ask_fix_saved(callback: CallbackQuery, state: FSMContext) -> None:
    async with get_session() as session:
        meal = await _own_meal(session, callback, CB_FIX)
    if meal is None:
        await callback.answer("Этой записи уже нет")
        await callback.message.edit_reply_markup(reply_markup=None)
        return
    if not meal.weight_g:
        await callback.answer("У этой записи нет веса — её можно только отменить",
                              show_alert=True)
        return
    await state.set_state(FoodStates.fixing_saved)
    await state.set_data({"fix_meal_id": meal.id})
    await callback.message.answer(
        f"Сколько граммов на самом деле? Сейчас записано {_num(meal.weight_g)} г "
        f"«{meal.name}». Например: 250"
    )
    await callback.answer()


@router.message(FoodStates.fixing_saved, F.text, ~F.text.in_(MENU_TEXTS))
async def apply_fix_saved(message: Message, state: FSMContext) -> None:
    weight = parse_float(message.text)
    if weight is None or not (MIN_WEIGHT_G <= weight <= MAX_WEIGHT_G):
        await message.answer(
            f"Введи вес числом от {MIN_WEIGHT_G:.0f} до {MAX_WEIGHT_G:.0f} г, например: 250"
        )
        return

    meal_id = (await state.get_data()).get("fix_meal_id")
    await state.clear()
    async with get_session() as session:
        meal = await session.get(Meal, meal_id) if meal_id else None
        if meal is None or meal.user_id != message.from_user.id or not meal.weight_g:
            await message.answer("Этой записи уже нет — поправить нечего.")
            return
        meal = await rescale_meal(session, meal, weight)
        name, calories, meal_id = meal.name, meal.calories, meal.id
        user = await session.get(User, message.from_user.id)
        totals, *_ = await _sync_day(session, user)
        norm = user.daily_calories

    await message.answer(
        f"✏️ Исправлено: {name} — {_num(weight)} г, ≈ {_num(calories)} ккал\n\n"
        f"🔥 Сегодня {_num(totals.calories)}" + (f" / {norm} ккал" if norm else " ккал"),
        reply_markup=saved_keyboard(meal_id),
    )


def _render_day_summary(analysis, meal_type_label, totals, norms, game=None,
                        *, cheetah=None) -> str:
    calories_norm, protein_norm, fat_norm, carbs_norm, fiber_norm = norms
    lines = [f"✅ Записал: {analysis.name} ({meal_type_label})", ""]

    if calories_norm:
        lines += [
            f"🔥 {_num(totals.calories)} / {calories_norm} ккал",
            f"{render_progress_bar(totals.calories, calories_norm)} · "
            f"{format_remaining(totals.calories, calories_norm)} ккал",
            "",
        ]
    lines += [
        f"🥩 Б {_num(totals.protein_g)} / {protein_norm or '—'} г",
        f"🥑 Ж {_num(totals.fat_g)} / {fat_norm or '—'} г",
        f"🍚 У {_num(totals.carbs_g)} / {carbs_norm or '—'} г",
        f"🥦 Клетчатка {_num(totals.fiber_g)} / {fiber_norm or '—'} г",
    ]
    lines += turn_service.game_lines(game)
    if cheetah is not None:
        lines += ["", f"{cheetah.emoji} {cheetah.line}"]
    return "\n".join(lines)


@router.callback_query(FoodStates.confirming, F.data == CB_CANCEL)
async def cancel_food(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Не записал ❌")
    await callback.answer()
