"""Чтобы шаги приходили с телефона сами.

Ограничение, вокруг которого всё построено: мини-приложение внутри Telegram
не может читать «Здоровье» — ни на айфоне, ни на Android. Это не вопрос
согласия человека, такого канала не существует у веб-страницы вовсе.

Обход: телефон присылает шаги сам, по личной ссылке. Ключ в ней — не пароль:
по нему можно только записать себе шаги за день и нельзя прочитать ничего.
Проверяется в основном это.
"""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from models import ActivityLevelEnum, Base, GenderEnum, GoalEnum, StepLog, User
from services import step_sync
from services import steps as step_service

USER = 1
OTHER = 2


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for user_id in (USER, OTHER):
            session.add(User(
                id=user_id, full_name="Лилия", gender=GenderEnum.FEMALE, age=30,
                height_cm=165, current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
                activity_level=ActivityLevelEnum.MODERATE, daily_steps=8000,
                onboarding_completed=True, timezone="Europe/Moscow"))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


@pytest.fixture(autouse=True)
def clean():
    step_service.forget_pushes()
    yield
    step_service.forget_pushes()


# --- Ключ ------------------------------------------------------------------

def test_the_key_is_personal_and_stable():
    async def scenario():
        async with db() as session:
            user = await session.get(User, USER)
            first = await step_service.sync_token(session, user)
            assert len(first) == step_service.TOKEN_LENGTH
            # Повторный вызов не выдаёт новый: ссылка уже отдана телефону.
            assert await step_service.sync_token(session, user) == first

            other = await session.get(User, OTHER)
            assert await step_service.sync_token(session, other) != first
    run(scenario)


def test_changing_the_key_kills_the_old_link():
    """Так отзывают ссылку, которая куда-то утекла."""
    async def scenario():
        async with db() as session:
            user = await session.get(User, USER)
            old = await step_service.sync_token(session, user)
            new = await step_service.sync_token(session, user, renew=True)

            assert new != old
            assert await step_service.by_token(session, old) is None
            assert (await step_service.by_token(session, new)).id == USER
    run(scenario)


def test_an_unknown_key_belongs_to_nobody():
    async def scenario():
        async with db() as session:
            assert await step_service.by_token(session, "выдуманный") is None
            assert await step_service.by_token(session, "") is None
    run(scenario)


# --- Ограничитель ----------------------------------------------------------

def test_a_looping_automation_is_stopped():
    """Расписание шлёт раз в несколько часов; зациклившееся — тысячи раз."""
    allowed = sum(step_service.push_allowed("ключ")
                  for _ in range(step_service.SYNC_PER_HOUR + 20))
    assert allowed == step_service.SYNC_PER_HOUR


def test_the_limit_lets_go_after_an_hour():
    now = datetime.now(timezone.utc)
    for _ in range(step_service.SYNC_PER_HOUR):
        step_service.push_allowed("ключ", now=now)

    assert step_service.push_allowed("ключ", now=now) is False
    assert step_service.push_allowed("ключ", now=now + timedelta(hours=1, minutes=1))


def test_the_limit_is_personal():
    for _ in range(step_service.SYNC_PER_HOUR):
        step_service.push_allowed("первый")
    assert step_service.push_allowed("второй") is True


# --- Ссылка и инструкция ---------------------------------------------------

def test_the_link_ends_where_the_number_goes(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "https://aura.example/")
    link = step_sync.link_for("КЛЮЧ")
    assert link == "https://aura.example/hook/steps/КЛЮЧ?steps="
    assert link.endswith("=") , "число подставляется в конец — так проще в «Командах»"


def test_without_a_site_there_is_no_link_and_it_is_explained(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "")
    assert step_sync.link_for("КЛЮЧ") == ""
    assert "кнопкой" in step_sync.instructions("")


def test_the_instruction_says_why_and_how_and_about_safety(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "https://aura.example")
    text = step_sync.instructions(step_sync.link_for("КЛЮЧ"))

    assert "«Команды»" in text and "Здоровь" in text
    # Что делает присылку автоматической. Раньше это было расписание, теперь —
    # запуск при открытии Telegram: он проверен на живом айфоне и даёт свежие
    # шаги тогда, когда на них смотрят. Проверяется механизм, а не время.
    assert "Telegram" in text and "Автоматизация" in text
    assert "Android" in text
    assert "поменяй" in text, "человек должен знать, что ссылку можно отозвать"
    assert "КЛЮЧ" in text


def test_the_instruction_does_not_promise_a_direct_connection(monkeypatch):
    """Обещать «подключимся к Здоровью» нельзя: это неправда."""
    monkeypatch.setattr(config, "WEBAPP_URL", "https://aura.example")
    text = step_sync.instructions(step_sync.link_for("КЛЮЧ")).lower()
    for lie in ("подключим", "подключится к здоровью", "синхронизируется автоматически с"):
        assert lie not in text, lie


# --- Инструкция: карточки --------------------------------------------------


def test_the_instruction_names_the_actions_that_were_actually_tested():
    """Первая версия не собралась ни у кого, кроме автора.

    Она называла действия, которых в этой версии iOS нет: «Найти образцы
    состояния здоровья» со «Способ → Сумма». На живом айфоне данные берёт
    «Найти данные Здоровья», а сумму считает отдельное «Подсчитать
    статистику». Проверять надо оба конца: что верное названо и что
    неверное больше не названо.
    """
    text = step_sync.as_text()
    for action in ("Найти данные Здоровья", "Подсчитать статистику",
                   "Получить содержимое URL"):
        assert action in text, action
    for wrong in ("Найти образцы состояния здоровья", "Способ»"):
        assert wrong not in text, wrong


def test_the_automations_only_launch_the_ready_shortcut():
    """Ради этого инструкция и переписана.

    Пока вся работа лежала внутри автоматизации, вторая автоматизация
    означала вторую такую же сборку с нуля — и шаги чаще раза в сутки были
    практически недостижимы. Теперь автоматизация только запускает готовую
    команду, и вторая стоит четырёх касаний.
    """
    cards = step_sync.CARDS
    first = next(i for i, card in enumerate(cards)
                 if "Автоматизация»" in " ".join(card.steps))
    tail = " ".join(" ".join(card.steps) + " " + card.note
                    for card in cards[first:])

    assert "Запустить быструю команду" in tail
    assert step_sync.SHORTCUT_NAME in tail
    # Ни одного действия сборки: иначе это снова полная сборка.
    assert "Найти данные Здоровья" not in tail
    assert "Подсчитать статистику" not in tail


def test_the_shortcut_is_named_before_any_automation_needs_it():
    """Автоматизация ищет команду по имени. Если имя дают позже — не найдёт."""
    titles = [card.title for card in step_sync.CARDS]
    named = next(i for i, title in enumerate(titles)
                 if step_sync.SHORTCUT_NAME in title)
    first_launch = next(i for i, card in enumerate(step_sync.CARDS)
                        if "Запустить быструю команду" in " ".join(card.steps))
    assert named < first_launch


def test_the_person_is_told_to_allow_sending_always():
    """Шаг, без которого автоматика тихо останавливается.

    При первой отправке телефон спрашивает разрешение на обращение к сайту.
    Ответив «Разрешить один раз», человек получит этот вопрос и при
    автоматическом запуске — а там на него некому ответить: команда просто
    встанет, и шаги перестанут приходить, ничего не сообщив. Проверено на
    живом айфоне.
    """
    text = step_sync.as_text()
    assert "Разрешать всегда" in text
    card = next(card for card in step_sync.CARDS
                if "Разрешать всегда" in " ".join(card.steps))
    assert "переспрашивать" in card.note or "остановится" in card.note


def test_the_marking_of_unverified_steps_agrees_with_the_words():
    """Пометка и текст обязаны говорить одно и то же.

    Дневной запуск по открытию Telegram сначала стоял непроверенным — и был
    помечен. Лилия проверила его на живом айфоне, пометка снята. Опасны оба
    расхождения: помеченная карточка без объяснения и карточка, которая
    словами признаётся в непроверенности, но выглядит как проверенная.
    """
    for card in step_sync.CARDS:
        says = "не проверял" in card.note.lower()
        assert says == card.unverified, card.title


def test_the_optional_night_run_avoids_midnight():
    """Ночной запуск — страховка на дни без Telegram, и он необязателен.

    Но если человек его делает, время должно быть до полуночи: в 00:00
    начинается новый день, и сумма шагов будет пустой.
    """
    notes = " ".join(card.note for card in step_sync.CARDS)
    assert "23:50" in notes
    assert "Не ставь 00:00" in notes


# --- Готовая команда по ссылке ---------------------------------------------


def test_without_a_ready_shortcut_nothing_changes():
    """Пока готовой команды нет, инструкция та же, что и была."""
    assert step_sync.deck(False) == step_sync.CARDS
    assert len(step_sync.CARDS) == 10


def test_the_ready_shortcut_removes_exactly_the_building():
    """Собранную команду не собирают заново.

    Значит, исчезают ровно карточки сборки — и ни одна другая: ни
    разрешения, ни автоматизация от готовой команды не появляются сами.
    """
    short = step_sync.deck(True)
    assert step_sync.READY in short
    assert len(short) == 6

    gone = {card.title for card in step_sync.CARDS} - {c.title for c in short}
    assert gone == {card.title for card in step_sync.CARDS if card.build}

    tail = " ".join(" ".join(card.steps) + " " + card.note for card in short)
    assert "Разрешать всегда" in tail, "разрешения нужны и готовой команде"
    assert "Запустить быструю команду" in tail, "автоматизацию всё равно делать"


def test_the_ready_shortcut_warns_about_someone_elses_link():
    """Единственная опасность общей команды.

    Если внутри неё осталась чужая личная ссылка, шаги всех, кто её
    поставил, уходят одному человеку — молча и без единого признака
    поломки. Проверить это может только сам человек, открыв действие «URL».
    """
    note = step_sync.READY.note.lower()
    assert "чужая" in note or "чужой" in note
    assert "url" in note


def test_the_ready_card_asks_to_paste_the_personal_link():
    """Общая команда не может знать твою ссылку — её вставляют при установке."""
    steps = " ".join(step_sync.READY.steps).lower()
    assert "вставь" in steps and "ссылк" in steps


# --- Проверка подключения --------------------------------------------------


def test_nothing_arrived_yet_is_said_plainly():
    state = step_sync.check(minutes_since=None, today_steps=0, local_hour=12)
    assert state.code == "never" and not state.ok
    assert "не поступали" in state.title


def test_a_working_connection_shows_the_number_and_the_time():
    state = step_sync.check(minutes_since=7, today_steps=4210, local_hour=12)
    assert state.code == "ok" and state.ok
    assert "4210" in state.title
    assert "7 минут назад" in state.note


def test_zero_right_after_midnight_is_not_the_persons_fault():
    """Ноль — законное число. Ночью в «Здоровье» просто нет записей."""
    state = step_sync.check(minutes_since=20, today_steps=0, local_hour=2)
    assert state.code == "early"
    assert state.ok, "связь есть — пугать нечем"


def test_zero_in_the_afternoon_points_at_the_permission():
    """Днём ноль почти всегда значит одно: «Командам» не разрешили читать шаги."""
    state = step_sync.check(minutes_since=20, today_steps=0, local_hour=15)
    assert state.code == "zero" and not state.ok
    assert "разреш" in state.note.lower()


def test_one_missed_night_is_not_a_broken_connection():
    """Телефон мог быть выключен. Пугать за это нельзя."""
    day = 24 * 60
    assert step_sync.check(minutes_since=day + 60, today_steps=0,
                           local_hour=12).code != "silent"
    assert step_sync.check(minutes_since=3 * day, today_steps=0,
                           local_hour=12).code == "silent"


def test_the_time_is_said_in_russian():
    """«11 минуты назад» — то, из-за чего перестают верить остальному тексту."""
    assert step_sync.ago(0) == "только что"
    assert step_sync.ago(1) == "1 минуту назад"
    assert step_sync.ago(11) == "11 минут назад"
    assert step_sync.ago(22) == "22 минуты назад"
    assert step_sync.ago(60) == "1 час назад"
    assert step_sync.ago(5 * 60) == "5 часов назад"
    assert step_sync.ago(50 * 60) == "2 дня назад"


# --- Записи с телефона -----------------------------------------------------

def test_a_pushed_number_is_marked_as_coming_from_the_phone():
    async def scenario():
        async with db() as session:
            await step_service.record(session, USER, 9200,
                                      source=step_service.SOURCE_PHONE)
            row = (await session.execute(
                __import__("sqlalchemy").select(StepLog))).scalars().one()
            assert row.source == step_service.SOURCE_PHONE
            assert await step_service.last_sync(session, USER) is not None
    run(scenario)


def test_a_hand_typed_number_is_not_counted_as_a_sync():
    async def scenario():
        async with db() as session:
            await step_service.record(session, USER, 5000)
            assert await step_service.last_sync(session, USER) is None
    run(scenario)
