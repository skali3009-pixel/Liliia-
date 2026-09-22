"""Кнопка меню обязана вырывать человека из недописанного ответа.

Правило в проекте было записано давно и считалось работающим: у шагов,
жалоб и профиля стоят обработчики «кнопка меню важнее недописанного
ответа» — они чистят состояние и отдают нажатие дальше через `SkipHandler`.

**Они не работали.** Поймано не чтением и не этим тестом, а Лилией на живом
боте: она нажала «Добавить еду», потом «Воду» — и получила разбор еды.

Почему. `raw_state` кладётся в данные события один раз, до всех
обработчиков. `state.clear()` пишет в хранилище, но эту копию не трогает.
Значит после `SkipHandler` следующий обработчик в том же роутере проверяет
свой `StateFilter` по **устаревшему** состоянию, совпадает — и съедает
нажатие. Ни сообщения, ни отказа: ответ не про то.

Лечится не порядком и не очисткой, а явным отказом в самом фильтре
потребителя: `~F.text.in_(MENU_TEXTS)`. Тогда он просто не совпадает,
и событие честно уходит дальше по роутерам.

Проверяется настоящей доставкой события — `propagate_event` с живым
состоянием. Сторож, читающий исходник, здесь бессилен: он видел бы и
очистку, и `SkipHandler`, и остался бы доволен на коде, который съедает
нажатия. Ровно так и вышло в первый раз.
"""

import asyncio
from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from handlers import feedback, food, profile, steps
from handlers.feedback import FeedbackStates
from handlers.food import FoodStates
from handlers.profile import ProfileStates
from handlers.steps import StepStates
from keyboards.main_menu import MENU_TEXTS, main_menu_keyboard

# Каждое состояние, в котором бот ждёт текст, и тот, кто этот текст ест.
# Имя едока названо явно: без него проверка «никто не съел» ловила бы и
# правильную работу — нажатие «Профиля» законно обрабатывает `show_profile`,
# и это не поломка, а ровно то, чего мы хотим.
СЦЕНАРИИ = [
    ("ждём текст еды", food.router, FoodStates.waiting_input, "handle_food_text"),
    ("правим вес блюда", food.router, FoodStates.correcting_weight, "apply_weight"),
    ("правим название блюда", food.router, FoodStates.correcting_dish,
     "apply_correct_dish"),
    ("ждём число шагов", steps.router, StepStates.waiting_number, "take_number"),
    ("пишем жалобу", feedback.router, FeedbackStates.writing, "take_report"),
    ("отвечаем на жалобу", feedback.router, FeedbackStates.answering, "send_answer"),
    ("правим целевой вес", profile.router, ProfileStates.target_weight,
     "save_target_weight"),
    ("правим рост", profile.router, ProfileStates.height, "save_height"),
    ("правим возраст", profile.router, ProfileStates.age, "save_age"),
    ("правим аллергии", profile.router, ProfileStates.allergies, "save_allergies"),
]


def _кто_сработал(роутер, состояние, текст):
    """Настоящая доставка события. Возвращает имена сработавших и остаток состояния."""
    сработали = []
    прежние = [(h, h.callback) for h in роутер.message.handlers]

    def обёртка(оригинал, имя):
        async def вызов(*args, **kwargs):
            сработали.append(имя)
            return await оригинал(*args, **kwargs)
        return вызов

    for h, оригинал in прежние:
        h.callback = обёртка(оригинал, getattr(оригинал, "__name__", "?"))

    async def прогон():
        state = FSMContext(storage=MemoryStorage(),
                           key=StorageKey(bot_id=1, chat_id=1, user_id=1))
        await state.set_state(состояние)
        письмо = SimpleNamespace(
            text=текст, from_user=SimpleNamespace(id=1), photo=None, voice=None,
            content_type="text", caption=None, chat=SimpleNamespace(id=1))
        # `bot` обязателен: фильтры команд требуют его позиционно, и без
        # него проверка падает на первом же `Command` — а он стоит раньше
        # тех, кого мы проверяем. Первая версия теста на этом и обманулась:
        # прогон обрывался, и выходило «ответ никто не принял».
        данные = {"state": state, "raw_state": await state.get_state(),
                  "event_from_user": письмо.from_user,
                  "bot": SimpleNamespace(id=1, username="bot")}
        try:
            await роутер.propagate_event(update_type="message", event=письмо,
                                         **данные)
        except Exception:
            # Настоящий обработчик уходит в сеть или в базу и падает — нам
            # довольно того, что он вообще был вызван.
            pass
        return сработали, await state.get_state()

    try:
        return asyncio.run(прогон())
    finally:
        for h, оригинал in прежние:
            h.callback = оригинал


@pytest.mark.parametrize("подпись,роутер,состояние,едок", СЦЕНАРИИ,
                         ids=[с[0] for с in СЦЕНАРИИ])
def test_нажатие_кнопки_меню_не_съедается(подпись, роутер, состояние, едок):
    """Ни один сценарий не имеет права принять нажатие кнопки за ответ."""
    for кнопка in sorted(MENU_TEXTS):
        сработали, _ = _кто_сработал(роутер, состояние, кнопка)
        assert едок not in сработали, f"{подпись}: «{кнопка}» съел {едок}"


@pytest.mark.parametrize("подпись,роутер,состояние,едок", СЦЕНАРИИ,
                         ids=[с[0] for с in СЦЕНАРИИ])
def test_нажатие_кнопки_меню_отпускает_сценарий(подпись, роутер, состояние, едок):
    """Мало не съесть — надо ещё и выпустить.

    Иначе человек остаётся в ожидании числа: нажал «Воду», посмотрел воду,
    вернулся, написал слово — и оно молча уехало в поле профиля.
    """
    for кнопка in sorted(MENU_TEXTS):
        _, осталось = _кто_сработал(роутер, состояние, кнопка)
        assert осталось is None, f"{подпись}: после «{кнопка}» остался {осталось}"


@pytest.mark.parametrize("подпись,роутер,состояние,едок", СЦЕНАРИИ,
                         ids=[с[0] for с in СЦЕНАРИИ])
def test_обычный_ответ_по_прежнему_принимается(подпись, роутер, состояние, едок):
    """Отказ должен быть узким: всё, кроме кнопок, обязано доходить.

    Без этой проверки «починить» можно было бы, перестав принимать текст
    вовсе, — и тест на съеденные нажатия остался бы зелёным.
    """
    сработали, _ = _кто_сработал(роутер, состояние, "120")
    assert едок in сработали, f"{подпись}: обычный ответ не дошёл до {едок}"


def test_список_сценариев_не_отстал_от_кода():
    """Появился новый сценарий, ждущий текст, — он обязан попасть сюда.

    Иначе следующий такой обработчик заведут без отказа, и половина меню
    снова начнёт тихо съедаться.
    """
    import inspect
    import re

    известные = {с.state for _, _, с, _ in СЦЕНАРИИ}
    пропущены = []

    for модуль in (food, steps, feedback, profile):
        исходник = inspect.getsource(модуль)
        for строка in re.findall(r"@router\.message\(([^)]*States\.[^)]*)\)",
                                 исходник):
            if "F.text" not in строка:
                continue
            состояние = строка.split(",")[0].strip()
            if "." not in состояние:
                continue
            класс, поле = состояние.split(".")
            найден = getattr(getattr(модуль, класс, None), поле, None)
            if найден is None or найден.state in известные:
                continue
            пропущены.append(f"{модуль.__name__}: {состояние}")

    assert not пропущены, f"не проверены сценарии: {пропущены}"


def test_отказ_смотрит_на_тот_же_список_что_и_клавиатура():
    """Список отказа и клавиатура обязаны описывать одни и те же кнопки."""
    подписи = {к.text for ряд in main_menu_keyboard().keyboard for к in ряд}
    assert подписи == MENU_TEXTS
