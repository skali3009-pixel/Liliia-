"""Слайды знакомства и то, что бот обещает на первом экране.

Анкета — девять вопросов подряд, и до приложения человек ещё не дошёл:
отваливаются именно здесь. Слайды — единственное, что в этом месте
объясняет, ради чего отвечать. А стартовое сообщение — единственное место,
где человек вообще узнаёт, на что соглашается.
"""

import asyncio
import re
import types
from pathlib import Path

import pytest

from handlers import legal
from services.slides import SLIDES, SLIDES_DIR, send_slide, slide_path

КОРЕНЬ = Path(__file__).resolve().parents[1]
LEGAL = (КОРЕНЬ / "handlers" / "legal.py").read_text(encoding="utf-8")
ONBOARDING = (КОРЕНЬ / "handlers" / "onboarding.py").read_text(encoding="utf-8")

# Где слайду стоять позволено — и больше нигде.
РАЗРЕШЕНО = {"legal.py", "onboarding.py"}


class ФейковоеСообщение:
    def __init__(self, падает=False):
        self.отправлено = []
        self.падает = падает

    async def answer_photo(self, файл, **прочее):
        if self.падает:
            raise RuntimeError("Telegram не принял картинку")
        self.отправлено.append(файл)


def test_all_three_slides_exist_as_files():
    """Картинки лежат в репозитории: на сервере браузера нет и быть не должно.

    Отрисовывает их `promo/slides.py` — тем же шрифтом и той же палитрой,
    что и приложение.
    """
    assert set(SLIDES) == {"what_is_inside", "why_questions", "in_chat_too"}
    for имя in SLIDES:
        путь = slide_path(имя)
        assert путь is not None, f"нет файла слайда {имя}"
        assert путь.stat().st_size > 30_000, (имя, путь.stat().st_size)


def test_the_slides_are_square_and_not_oversized():
    """Квадрат Telegram показывает на телефоне целиком, не заставляя нажимать.

    А вытянутый холст оставлял внизу пустую треть — содержимого столько нет.
    """
    from PIL import Image

    for имя in SLIDES:
        with Image.open(slide_path(имя)) as кадр:
            assert кадр.size == (1080, 1080), (имя, кадр.size)


def test_each_slide_shows_up_once_and_only_where_it_belongs():
    """Слайд после каждого вопроса — это не помощь, а мигание."""
    где = {путь.name for путь in (КОРЕНЬ / "handlers").glob("*.py")
           if "send_slide(" in путь.read_text(encoding="utf-8")}
    assert где == РАЗРЕШЕНО, где ^ РАЗРЕШЕНО

    весь = LEGAL + ONBOARDING
    for имя in SLIDES:
        assert весь.count(f'"{имя}"') == 1, имя


def test_the_slides_stand_where_a_person_gives_up():
    """Порядок не случаен: до первого вопроса, на середине, после анкеты."""
    # «Что внутри» — сразу после согласия, следом за приветственным кружком.
    кусок = LEGAL.split('send_slide(callback.message, "what_is_inside")', 1)[0]
    assert 'send_circle(callback.message, "hello")' in кусок

    # «Почему столько вопросов» — после целевого веса, перед активностью.
    кусок = ONBOARDING.split('send_slide(message, "why_questions")', 1)
    assert "target_weight_kg=weight" in кусок[0]
    assert "уровень активности" in кусок[1][:400]

    # «И в чате тоже» — после того, как анкета записана.
    кусок = ONBOARDING.split('send_slide(message, "in_chat_too")', 1)[0]
    assert "user.onboarding_completed = True" in кусок


def test_the_slides_are_awaited():
    """Забытый await — это «слайд не пришёл», и никакой ошибки."""
    for текст in (LEGAL, ONBOARDING):
        for строка in текст.splitlines():
            if "send_slide(" in строка and "import" not in строка:
                до = строка.split("send_slide(")[0]
                assert до.rstrip().endswith("await"), строка


def test_a_broken_slide_never_stops_the_registration():
    """Человек пришёл заводить профиль, а не смотреть картинки."""
    сообщение = ФейковоеСообщение(падает=True)
    assert asyncio.run(send_slide(сообщение, "what_is_inside")) is False


def test_an_unknown_slide_is_a_mistake_in_the_code_and_says_so():
    with pytest.raises(KeyError):
        slide_path("kartinka")


# --- Что бот обещает на первом экране ------------------------------------

def test_the_welcome_names_what_the_bot_actually_has():
    """Прежний список молчал о половине бота.

    Ни заготовок, ни рецептов, ни «сфоткай полку», ни того, что всё главное
    работает в чате без приложения. Человек соглашается на обработку данных
    о здоровье — и должен знать, ради чего.
    """
    текст = legal.welcome_text().lower()
    for слово in ("фото", "голос", "заготовк", "рецепт", "полку", "шаг",
                  "женский календарь", "объём", "чате"):
        assert слово in текст, слово


def test_the_welcome_counts_match_the_real_catalogue():
    """Числа в обещании — это обещание. Разойдутся с каталогом — станут ложью."""
    текст = legal.welcome_text()
    from seed.exercise_ids import EXERCISE_IDS

    коды = EXERCISE_IDS.values() if isinstance(EXERCISE_IDS, dict) else EXERCISE_IDS
    assert f"{len(set(коды))} упражнени" in текст, текст

    числа = re.findall(r"(\d+) программ", текст)
    assert числа, текст
    # Берём сам справочник, а не выискиваем строки в загрузчике: разметка
    # загрузчика меняется, а этот словарь — и есть список программ.
    # «Я занималась сама» лежит отдельно (CARDIO) и программой не является.
    from seed.workout_programs import PROGRAMS
    assert int(числа[0]) == len(PROGRAMS), (числа[0], len(PROGRAMS))


def test_the_welcome_still_carries_the_legal_part_unchanged():
    """Юридический текст Лилия решила оставить как есть."""
    текст = legal.welcome_text()
    assert "Это не медицинская услуга" in текст
    assert "не заменяют консультацию врача" in текст
    assert "тебе есть 18 лет" in текст
    assert "включая сведения о здоровье" in текст
    assert "Владелец:" in текст


def test_the_welcome_fits_one_telegram_message():
    """Длиннее 4096 знаков бот просто не ответил бы."""
    assert len(legal.welcome_text()) <= 4096


def test_the_welcome_promises_nothing_it_cannot_do():
    """Те же правила, что у техники и тура: ни обещаний результата, ни диагнозов."""
    текст = legal.welcome_text().lower()
    for запрет in ("похуде", "гарантирова", "избавит", "результат за",
                   "вылеч", "сожжёт"):
        assert запрет not in текст, запрет


# --- Питание: две кнопки, которые путали даже владелицу -------------------

def test_vegan_and_vegetarian_say_how_they_differ():
    """Лилия увидела их рядом и решила, что кнопка продублировалась.

    Диеты разные — у вегана нет ни молока, ни яиц, — но если этого не видно
    хозяйке бота, то человеку в анкете не видно тем более.
    """
    from keyboards.onboarding import DIET_LABELS
    from models import DietTypeEnum

    веган = DIET_LABELS[DietTypeEnum.VEGAN]
    вег = DIET_LABELS[DietTypeEnum.VEGETARIAN]
    assert "молок" in веган.lower(), веган
    assert "молок" not in вег.lower(), вег
    assert веган != вег

    # И ни одна подпись не должна обрезаться на узком экране.
    for подпись in DIET_LABELS.values():
        assert len(подпись) <= 32, (подпись, len(подпись))
