"""Музыка, источники переходов и минимальный учёт.

Три вещи, добавленные к работающему боту 20 сентября. Общее у них одно: ни
одна не должна менять рабочий сценарий. Поэтому здесь проверяется не только
то, что новое работает, но и то, что старое не тронуто — анкета, приглашения
и неизвестный параметр `/start`.

Отдельно проверяется то, что ломается молча: повторная доставка события,
пустой ответ подбора, засчитанный за пользу, и метка, выданная за источник
привлечения человека, который был заведён раньше.
"""

import asyncio
import contextlib
import datetime as дата
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from models import Base, MarketingEvent, User
from services import analytics, sources

КОРЕНЬ = Path(__file__).resolve().parent.parent
ОНА, ДРУГАЯ, ВЛАДЕЛИЦА = 1001, 1002, 1003


def run(scenario):
    return asyncio.run(scenario())


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for uid in (ОНА, ДРУГАЯ, ВЛАДЕЛИЦА):
            session.add(User(id=uid, full_name=f"Гостья {uid}"))
        await session.commit()
        yield session
    await engine.dispose()


class Человек:
    """То, что кладётся в поле пользователя: важны только два источника."""

    def __init__(self):
        self.first_source = None
        self.last_source = None


# --- 1. Музыка -------------------------------------------------------------

def test_кнопка_музыки_одна_и_ведёт_куда_названа(monkeypatch):
    from handlers.onboarding import open_app_keyboard

    monkeypatch.setattr(config, "WEBAPP_URL", "https://app.example")
    кнопки = [к for р in open_app_keyboard().inline_keyboard for к in р]
    музыка = [к for к in кнопки if к.url]

    assert len(музыка) == 1, [к.text for к in кнопки]
    assert "SCALIA" in музыка[0].text
    assert музыка[0].url == config.MUSIC_URL
    assert музыка[0].url.startswith("https://")


def test_музыка_выключается_настройкой(monkeypatch):
    """Чужой сервис может пропасть — убрать кнопку должно быть одним действием."""
    from handlers.onboarding import open_app_keyboard

    monkeypatch.setattr(config, "WEBAPP_URL", "https://app.example")
    monkeypatch.setattr(config, "MUSIC_URL", "")
    кнопки = [к for р in open_app_keyboard().inline_keyboard for к in р]
    assert not [к for к in кнопки if к.url]


def test_музыка_стоит_ровно_в_одном_месте():
    """«Кнопка повсюду» — это не предложение, а реклама.

    И ни одна другая часть бота не должна на неё смотреть: музыка ничего не
    задерживает и ни на что не влияет.
    """
    места = []
    for файл in (КОРЕНЬ / "handlers").rglob("*.py"):
        if "MUSIC_URL" in файл.read_text(encoding="utf-8"):
            места.append(файл.name)
    for файл in (КОРЕНЬ / "webapp").rglob("*"):
        if файл.is_file() and файл.suffix in {".py", ".js", ".html"}:
            assert "MUSIC_URL" not in файл.read_text(encoding="utf-8"), файл.name
    assert места == ["onboarding.py"], места


def test_музыке_ничего_не_обещают():
    """Ни подбора трека, ни влияния на пульс и вес."""
    текст = (config.MUSIC_BUTTON + " " +
             (КОРЕНЬ / "config.py").read_text(encoding="utf-8")).lower()
    кусок = текст.split("музыка scalia")[0][-1200:] + текст.split("music_url")[-1][:400]
    for запрет in ("подобранный трек", "под твой пульс", "похуде", "для похудения"):
        assert запрет not in кусок, запрет


# --- 2. Источники переходов ------------------------------------------------

def test_метки_роликов_распознаются():
    for метка in ("vk_a1_food", "vk_a2_move", "vk_a3_day", "vk_a4_progress",
                  "vk_b1_bridge"):
        assert sources.recognise(метка) == метка


def test_чужие_параметры_не_перехватываются():
    """`friend_` и `team_` уже заняты приглашениями и командами."""
    for чужое in ("friend_AbCdEf12", "team_XYZ", "instagram", "", None, "vk_a1"):
        assert sources.recognise(чужое) is None


def test_первый_источник_не_меняется():
    человек = Человек()
    sources.apply(человек, "vk_a1_food", is_new=True)
    sources.apply(человек, "vk_a3_day", is_new=False)

    assert человек.first_source == "vk_a1_food"
    assert человек.last_source == "vk_a3_day"


def test_обычный_старт_не_стирает_последнюю_метку():
    человек = Человек()
    sources.apply(человек, "vk_a2_move", is_new=True)
    sources.apply(человек, None, is_new=False)

    assert человек.last_source == "vk_a2_move"


def test_новый_без_метки_это_direct_unknown():
    человек = Человек()
    sources.apply(человек, "какая-то-ерунда", is_new=True)
    assert человек.first_source == sources.DIRECT
    assert человек.last_source is None


def test_заведённому_раньше_сегодняшняя_метка_не_источник():
    """Он уже был. Записать ему сегодняшний ролик — нарисовать себе привлечение."""
    человек = Человек()
    sources.apply(человек, "vk_a4_progress", is_new=False)

    assert человек.first_source == sources.EXISTING
    # Метку при этом не теряем — она просто учитывается отдельно.
    assert человек.last_source == "vk_a4_progress"


# --- 3. Учёт ---------------------------------------------------------------

def test_повторная_доставка_запуска_не_удваивает():
    async def scenario():
        async with db() as session:
            for _ in range(3):
                await analytics.note(session, ОНА, analytics.BOT_START,
                                     kind=analytics.NEW_PROFILE, once="once_a_day")
            await session.commit()

            строка = (await session.execute(select(MarketingEvent))).scalar_one()
            assert строка.count == 1
    run(scenario)


def test_завершение_анкеты_считается_раз_в_жизни():
    """Раз в жизни, а не раз в день.

    Проверять двумя вызовами подряд бесполезно: их одинаково остановит и
    правило «раз в сутки». Поэтому одна отметка ставится вчерашним днём —
    и видно, что сегодняшний вызов не заводит вторую.
    """
    async def scenario():
        async with db() as session:
            вчера = analytics._today() - дата.timedelta(days=1)
            session.add(MarketingEvent(user_id=ОНА,
                                       event=analytics.PROFILE_COMPLETED,
                                       kind="", day=вчера, count=1))
            await session.commit()

            снова = await analytics.note(session, ОНА, analytics.PROFILE_COMPLETED,
                                         once="once_ever")
            await session.commit()

            assert снова is False
            строки = (await session.execute(select(MarketingEvent))).scalars().all()
            assert len(строки) == 1 and строки[0].day == вчера
    run(scenario)


def test_новое_действие_учитывается_отдельно():
    """Второй записанный за день приём пищи — второе действие, а не дубль."""
    async def scenario():
        async with db() as session:
            await analytics.useful_action(session, ОНА, "meal")
            await analytics.useful_action(session, ОНА, "meal")
            await session.commit()

            действия = (await session.execute(
                select(MarketingEvent).where(
                    MarketingEvent.event == analytics.ACTION_COMPLETED)
            )).scalar_one()
            assert действия.count == 2

            # А «первое действие» и «активный день» остаются по одному.
            for событие in (analytics.FIRST_ACTION, analytics.ACTIVE_DAY):
                строка = (await session.execute(
                    select(MarketingEvent).where(MarketingEvent.event == событие)
                )).scalar_one()
                assert строка.count == 1, событие
    run(scenario)


def test_виды_действий_не_смешиваются():
    async def scenario():
        async with db() as session:
            for вид in ("meal", "cube", "measure", "workout"):
                await analytics.useful_action(session, ОНА, вид)
            await session.commit()

            итог = await analytics.report(session, days=7)
            assert итог.actions == {"meal": 1, "cube": 1, "measure": 1, "workout": 1}
            # Людей при этом один, а не четыре.
            assert итог.active_people == 1 and итог.first_actions == 1
    run(scenario)


def test_выдуманный_вид_действия_не_пишется():
    """Свободная строка здесь — вид, которого никто не заводил."""
    async def scenario():
        async with db() as session:
            await analytics.useful_action(session, ОНА, "открыл_экран")
            await session.commit()
            assert (await session.execute(select(MarketingEvent))).first() is None
    run(scenario)


def test_отчёт_не_смешивает_людей_с_событиями():
    async def scenario():
        async with db() as session:
            for _ in range(5):
                await analytics.useful_action(session, ОНА, "meal")
            await analytics.useful_action(session, ДРУГАЯ, "meal")
            await session.commit()

            итог = await analytics.report(session, days=7)
            assert итог.actions["meal"] == 6     # событий
            assert итог.active_people == 2        # людей
            assert итог.active_days == 2          # человеко-дней
    run(scenario)


def test_свои_номера_исключаются_из_отчёта():
    async def scenario():
        async with db() as session:
            await analytics.useful_action(session, ОНА, "meal")
            await analytics.useful_action(session, ВЛАДЕЛИЦА, "meal")
            await session.commit()

            итог = await analytics.report(session, days=7, exclude={ВЛАДЕЛИЦА})
            assert итог.active_people == 1
            assert итог.actions["meal"] == 1
    run(scenario)


def test_в_событиях_нет_ничего_личного():
    """Ни веса, ни возраста, ни еды, ни переписки — только номер, код и день."""
    колонки = {к.name for к in MarketingEvent.__table__.columns}
    assert колонки == {"id", "user_id", "event", "kind", "day", "count"}


def test_отчёт_называет_пояс_и_дату_начала_наблюдения():
    исходник = (КОРЕНЬ / "handlers" / "access.py").read_text(encoding="utf-8")
    кусок = исходник.split("async def marketing_report", 1)[1].split("\nasync def")[0]
    assert "REPORT_TZ" in кусок
    assert "STARTED_ON" in кусок
    assert analytics.REPORT_TZ == "Europe/Moscow"


def test_отчёт_закрыт_от_обычного_человека():
    исходник = (КОРЕНЬ / "handlers" / "access.py").read_text(encoding="utf-8")
    кусок = исходник.split("async def marketing_report", 1)[1].split("\nasync def")[0]
    голова = кусок.split("async with", 1)[0]
    assert "config.ADMIN_IDS" in голова and "return" in голова


# --- Что не должно было измениться ------------------------------------------

def test_анкета_и_приглашения_не_тронуты():
    """Учёт добавлен рядом, а не вместо: ни один шаг анкеты не убран."""
    from handlers import onboarding

    assert onboarding.ВСЕГО_ШАГОВ == 7
    исходник = (КОРЕНЬ / "handlers" / "onboarding.py").read_text(encoding="utf-8")
    # Приглашения и команды по-прежнему разбираются до всякого учёта.
    assert "_accept_invite(session, user.id, command.args)" in исходник
    assert "_accept_team(session, user.id, command.args)" in исходник
    # И прежнее поле метки продолжает заполняться.
    assert "user.referral = command.args[:64]" in исходник


def test_пустой_подбор_еды_не_считается_пользой():
    """Подбор отвечает 200 и пустым списком — это не выдача варианта."""
    исходник = (КОРЕНЬ / "webapp" / "api.py").read_text(encoding="utf-8")
    кусок = исходник.split("async def post_cube", 1)[1].split("\nasync def")[0]
    assert "if cubes:" in кусок
    между = кусок.split("if cubes:", 1)[1].split(
        'useful_action(session, user.id, "cube")', 1)[0]
    # Между проверкой и отметкой не должно быть ничего, кроме самого вызова:
    # любая строка здесь означала бы, что отметка стоит не под этой проверкой.
    assert между.replace("await", "").replace("analytics.", "").strip() == "", между
