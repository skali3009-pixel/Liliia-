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
    assert "23:50" in text, "без расписания присылка не автоматическая"
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
    launchers = [card for card in step_sync.CARDS
                 if "Автоматизация»" in " ".join(card.steps)]
    assert len(launchers) >= 2, "ночной запуск и дневной"
    for card in launchers:
        joined = " ".join(card.steps)
        assert "Запустить быструю команду" in joined
        assert step_sync.SHORTCUT_NAME in joined
        # Ни одного действия сборки: иначе это снова полная сборка.
        assert "Найти данные Здоровья" not in joined
        assert "Подсчитать статистику" not in joined


def test_the_shortcut_is_named_before_any_automation_needs_it():
    """Автоматизация ищет команду по имени. Если имя дают позже — не найдёт."""
    titles = [card.title for card in step_sync.CARDS]
    named = next(i for i, title in enumerate(titles)
                 if step_sync.SHORTCUT_NAME in title)
    first_launch = next(i for i, card in enumerate(step_sync.CARDS)
                        if "Запустить быструю команду" in " ".join(card.steps))
    assert named < first_launch


def test_what_was_not_tried_on_a_real_phone_is_marked():
    """Обещать непроверенное нельзя, а промолчать — значит соврать.

    Дневной запуск по открытию Telegram своими руками мы не проверяли.
    """
    unverified = [card for card in step_sync.CARDS if card.unverified]
    assert len(unverified) == 1
    assert "Telegram" in " ".join(unverified[0].steps)
    assert "не проверяли" in unverified[0].note


def test_the_night_run_avoids_midnight():
    """В 00:00 начинается новый день, и сумма шагов будет пустой."""
    night = " ".join(" ".join(card.steps) for card in step_sync.CARDS)
    assert "23:50" in night
    assert "00:00" not in night or "Не ставь 00:00" in \
        " ".join(card.note for card in step_sync.CARDS)


def test_the_chat_instruction_fits_into_one_telegram_message(monkeypatch):
    """У сообщения в Telegram потолок в 4096 знаков.

    Полная инструкция карточками в него не влезает: развернув её в чат
    целиком, бот просто не ответил бы — и узнали бы мы об этом от человека.
    Поэтому в чат идёт короткий пересказ, а подробности — в приложении.
    """
    monkeypatch.setattr(config, "WEBAPP_URL", "https://aura.example")
    text = step_sync.instructions(step_sync.link_for("К" * 22))
    assert len(text) < 4000, len(text)
    assert "в приложении" in text, "человека надо отправить туда, где подробно"


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
