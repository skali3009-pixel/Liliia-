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
#
# Кнопка «Музыка SCALIA» висела на чужом сообщении — том, где сказано, с чего
# начать. А следом уходят кружок, слайд, подарок за приглашение и предложение
# дозаполнить анкету: пять сообщений, и кнопка выше экрана раньше, чем до неё
# дотянутся. Кнопка на чужом сообщении живёт ровно столько, сколько это
# сообщение остаётся последним.

def test_кнопка_музыки_одна_и_ведёт_куда_названа():
    from services import music

    кнопки = [к for р in music.клавиатура().inline_keyboard for к in р]

    assert len(кнопки) == 1, [к.text for к in кнопки]
    assert кнопки[0].text == "Слушать SCALIA"
    assert кнопки[0].url == "https://music.yandex.ru/artist/26100573"
    assert кнопки[0].url == config.MUSIC_URL


def test_карточка_говорит_то_что_просили():
    """Текст карточки — слова Лилии о своём втором проекте, не пересказ."""
    from services import music

    assert music.ТЕКСТ.startswith("🎧 Ещё один мой проект — SCALIA")
    for кусок in ("Я Лилия, автор AURA и музыкального проекта SCALIA",
                  "Здесь собраны мои песни и визуальные истории",
                  "Если захотите послушать — откройте страницу проекта"):
        assert кусок in music.ТЕКСТ, кусок


def test_в_итоге_анкеты_музыки_больше_нет():
    """Иначе их станет две: одна на чужом сообщении, вторая на своём."""
    from handlers.onboarding import open_app_keyboard

    доска = open_app_keyboard()
    кнопки = [к for р in доска.inline_keyboard for к in р] if доска else []
    assert not [к for к in кнопки if к.url], [к.text for к in кнопки]
    assert not [к for к in кнопки if "SCALIA" in к.text]


def test_без_адреса_приложения_клавиатура_по_прежнему_пустая(monkeypatch):
    """Telegram ругается на пустую клавиатуру — функция обязана вернуть None.

    Это поведение было до музыки и обязано пережить её уход: поймано своей
    же проверкой сразу после первой правки.
    """
    from handlers.onboarding import open_app_keyboard

    monkeypatch.setattr(config, "WEBAPP_URL", "")
    assert open_app_keyboard() is None


def test_музыка_выключается_настройкой(monkeypatch):
    """Чужой сервис может пропасть — убрать карточку должно быть одним действием."""
    from services import music

    monkeypatch.setattr(config, "MUSIC_URL", "")
    assert music.клавиатура() is None


def test_карточка_приходит_последней():
    """Всё, что придёт после неё, уведёт её выше экрана — как и было.

    Проверяется порядок в самом коде: карточка обязана стоять ниже кружка,
    слайда и предложения дозаполнить анкету.
    """
    import inspect

    from handlers import onboarding

    исходник = inspect.getsource(onboarding._finish_onboarding)
    карточка = исходник.index("music.отправить")
    for раньше in ("send_circle", "send_slide", "_thank_for_invite",
                   "_offer_the_rest"):
        assert исходник.index(раньше) < карточка, раньше
    # И ничего после неё: хвост функции — только закрывающие строки.
    хвост = исходник[карточка:]
    assert "await " not in хвост.split("music.отправить(message)")[1]


def test_сбой_карточки_не_ломает_конец_анкеты():
    """Анкета обязана дойти до конца, чем бы ни кончилась отправка."""
    from services import music

    class Падает:
        async def answer(self, *a, **k):
            raise RuntimeError("Telegram недоступен")

    assert asyncio.run(music.отправить(Падает())) is False


def _только_код(исходник: str) -> str:
    """Исходник без комментариев и строк — одни исполняемые слова.

    Иначе сторож ловит объяснения вместо кода: первая версия проверки ниже
    упала на докстроке `handlers/music.py`, где `MUSIC_URL` назван по делу —
    и заставляла выбирать между понятным объяснением и зелёным тестом.
    """
    import io
    import tokenize

    куски = []
    for вид, текст, *_ in tokenize.generate_tokens(
            io.StringIO(исходник).readline):
        if вид not in (tokenize.COMMENT, tokenize.STRING):
            куски.append(текст)
    return " ".join(куски)


def test_музыка_стоит_ровно_в_одном_месте():
    """«Кнопка повсюду» — это не предложение, а реклама.

    Гарантия переехала вместе с кодом: адрес знает только `services/music.py`,
    обработчики и приложение на него не смотрят вовсе.
    """
    места = []
    for файл in (КОРЕНЬ / "services").rglob("*.py"):
        if "MUSIC_URL" in _только_код(файл.read_text(encoding="utf-8")):
            места.append(файл.name)
    assert места == ["music.py"], места

    for файл in (КОРЕНЬ / "handlers").rglob("*.py"):
        код = _только_код(файл.read_text(encoding="utf-8"))
        assert "MUSIC_URL" not in код, файл.name
    for файл in (КОРЕНЬ / "webapp").rglob("*"):
        if файл.is_file() and файл.suffix in {".py", ".js", ".html"}:
            assert "MUSIC_URL" not in файл.read_text(encoding="utf-8"), файл.name


def test_у_карточки_нет_ни_подписки_ни_счётчика():
    """Нажатие на URL-кнопку боту не приходит: считать здесь нечего.

    Показ кнопки — не переход, переход — не прослушивание. Любой счётчик
    здесь был бы выдуманной цифрой.
    """
    исходник = (КОРЕНЬ / "services" / "music.py").read_text(encoding="utf-8")
    код = "\n".join(с for с in исходник.splitlines()
                    if not с.strip().startswith("#"))
    for запрет in ("music_click", "callback_data", "analytics", "useful_action"):
        assert запрет not in код, запрет


def _строки(функция) -> str:
    """Что функция говорит человеку: её строковые литералы, без докстроки."""
    import ast
    import inspect
    import textwrap

    дерево = ast.parse(textwrap.dedent(inspect.getsource(функция)))
    докстрока = ast.get_docstring(дерево.body[0]) or ""
    найдено = [у.value for у in ast.walk(дерево)
               if isinstance(у, ast.Constant) and isinstance(у.value, str)
               and у.value != докстрока]
    return " ".join(найдено)


def test_музыке_ничего_не_обещают():
    """Ни подбора трека, ни влияния на пульс и вес.

    Это страница артиста, а не подобранная под человека музыка: подбора нет,
    и обещать его нечем. Смотрим на всё, что человек про музыку видит и
    читает, — карточку, подпись кнопки и объяснение настройки.
    """
    from handlers import music as команда
    from services import music

    # Смотрим на то, что человек читает, а не на исходник: в комментариях
    # запрещённые обороты стоят по делу — ими правило и объясняется, — и
    # сторож, который ловит объяснение, заставляет выбирать между понятным
    # комментарием и зелёным тестом. На этом уже обжигались дважды.
    видимое = " ".join([music.ТЕКСТ, music.КНОПКА,
                        _строки(команда.cmd_music)]).lower()
    for запрет in ("подобранный трек", "под твой пульс", "похуде",
                   "для похудения", "подберём музыку"):
        assert запрет not in видимое, запрет


# --- 2. Источники переходов ------------------------------------------------
#
# С 22.09.2026 метка называет площадку, а не ролик. Отдельная метка на каждое
# видео выглядела как способ сравнить ролики между собой, а на деле человек
# смотрит ролик в ленте, уходит и запускает бота через день из шапки профиля.
# «Из инстаграма» — правда; «из ролика А1» — то, чего мы не измеряли.

def test_все_шесть_площадок_распознаются():
    for метка in ("instagram_profile", "threads_profile", "tiktok_profile",
                  "youtube_profile", "vk_profile", "telegram_channel"):
        assert sources.recognise(метка) == метка
        assert метка in sources.PLATFORMS


def test_ссылки_собираются_на_все_площадки(monkeypatch):
    """Шесть ссылок, по одной на соцсеть, и все через ту же дверь.

    Адрес собирает `identity.start_link` — тот же, через который выходят
    приглашения. Свой `https://t.me/` здесь был бы вторым способом собрать
    ту же ссылку, и разошлись бы они молча.
    """
    monkeypatch.setattr(config, "BOT_USERNAME", "Scalia_fit_food_bot")
    собранные = sources.ссылки()

    assert len(собранные) == len(sources.PLATFORMS) == 6
    assert собранные == [
        ("Instagram", "https://t.me/Scalia_fit_food_bot?start=instagram_profile"),
        ("Threads", "https://t.me/Scalia_fit_food_bot?start=threads_profile"),
        ("TikTok", "https://t.me/Scalia_fit_food_bot?start=tiktok_profile"),
        ("YouTube", "https://t.me/Scalia_fit_food_bot?start=youtube_profile"),
        ("VK", "https://t.me/Scalia_fit_food_bot?start=vk_profile"),
        ("Telegram-канал", "https://t.me/Scalia_fit_food_bot?start=telegram_channel"),
    ]


def test_ссылка_не_выдумывается_пока_имя_бота_неизвестно(monkeypatch):
    """Ссылка в никуда хуже честного пробела."""
    monkeypatch.setattr(config, "BOT_USERNAME", "")
    assert all(адрес == "" for _, адрес in sources.ссылки())


def test_старые_метки_роликов_по_прежнему_понимаются():
    """Они уже разосланы и лежат в опубликованных постах.

    Перестань их понимать — и человек по старой ссылке станет
    `direct_unknown`: запись в базе окажется неправдой, и молча.
    """
    for метка in ("vk_a1_food", "vk_a2_move", "vk_a3_day", "vk_a4_progress",
                  "vk_b1_bridge"):
        assert sources.recognise(метка) == метка
        assert метка in sources.LEGACY


def test_старые_метки_не_выдаются_за_площадки():
    """Иначе в следующей публикации кто-нибудь снова поставит vk_a1_food."""
    for метка in sources.LEGACY:
        assert метка not in sources.PLATFORMS


def test_чужие_параметры_не_перехватываются():
    """`friend_` и `team_` уже заняты приглашениями и командами."""
    for чужое in ("friend_AbCdEf12", "team_XYZ", "instagram", "", None,
                  "vk_a1", "instagram_profile_2", "tiktok"):
        assert sources.recognise(чужое) is None


def test_первый_источник_не_меняется():
    человек = Человек()
    sources.apply(человек, "instagram_profile", is_new=True)
    sources.apply(человек, "tiktok_profile", is_new=False)

    assert человек.first_source == "instagram_profile"
    assert человек.last_source == "tiktok_profile"


def test_обычный_старт_не_стирает_последнюю_метку():
    человек = Человек()
    sources.apply(человек, "youtube_profile", is_new=True)
    sources.apply(человек, None, is_new=False)

    assert человек.last_source == "youtube_profile"


def test_новый_без_метки_это_direct_unknown():
    человек = Человек()
    sources.apply(человек, "какая-то-ерунда", is_new=True)
    assert человек.first_source == sources.DIRECT
    assert человек.last_source is None


def test_неизвестный_параметр_не_ломает_вход():
    """Вход обязан пройти штатно, что бы ни стояло после ?start=."""
    for мусор in (None, "", "   ", "?????", "vk_a1", "instagram",
                  "x" * 300, "друг", "start=instagram_profile"):
        человек = Человек()
        sources.apply(человек, мусор, is_new=True)
        assert человек.first_source == sources.DIRECT, мусор
        assert человек.last_source is None, мусор


def test_заведённому_раньше_сегодняшняя_метка_не_источник():
    """Он уже был. Записать ему сегодняшнюю площадку — нарисовать привлечение."""
    человек = Человек()
    sources.apply(человек, "vk_profile", is_new=False)

    assert человек.first_source == sources.EXISTING
    # Метку при этом не теряем — она просто учитывается отдельно.
    assert человек.last_source == "vk_profile"


def test_старая_ссылка_работает_ровно_как_новая():
    """Обратная совместимость — это не «не падает», а «ведёт себя так же»."""
    старый, новый = Человек(), Человек()
    sources.apply(старый, "vk_a2_move", is_new=True)
    sources.apply(новый, "vk_profile", is_new=True)

    assert старый.first_source == "vk_a2_move"
    assert новый.first_source == "vk_profile"
    assert старый.last_source == "vk_a2_move"


# --- 2б. Как источники выглядят в отчёте -----------------------------------

def test_отчёт_называет_площадки_словами():
    строки = "\n".join(sources.свод({"instagram_profile": 5,
                                     "telegram_channel": 2}))
    assert "Instagram: 5" in строки
    assert "Telegram-канал: 2" in строки
    assert "instagram_profile" not in строки


def test_старые_метки_в_отчёте_стоят_отдельно_и_не_склеиваются():
    """Склейка сделала бы отчёт короче, а историю — ложной.

    Пять разных меток превратились бы в одну, и отличить пришедшего по
    старой ссылке от пришедшего по новой стало бы нечем.
    """
    строки = "\n".join(sources.свод({"vk_profile": 3, "vk_a1_food": 2,
                                     "vk_b1_bridge": 1}))

    assert "VK: 3" in строки
    assert "vk_a1_food: 2" in строки, "старая метка обязана остаться видна"
    assert "vk_b1_bridge: 1" in строки
    assert "больше не выдаются" in строки
    # И один явный итог: складывать в уме владелице незачем.
    assert "Итого с VK (новая метка и старые): 6" in строки


def test_итог_по_vk_не_появляется_когда_старого_нет():
    """Строка про «старые метки» у того, у кого их нет, — просто шум."""
    строки = "\n".join(sources.свод({"vk_profile": 3}))
    assert "больше не выдаются" not in строки
    assert "Итого" not in строки


def test_в_отчёте_виден_каждый_записанный_человек():
    """Отчёт, который не сходится, хуже отчёта с непонятной строкой."""
    счёт = {"instagram_profile": 5, "vk_a1_food": 2, "vk_profile": 3,
            sources.DIRECT: 4, sources.EXISTING: 20, "ручная_правка": 1}
    строки = sources.свод(счёт)

    import re
    числа = [int(м) for с in строки
             for м in re.findall(r": (\d+)$", с.strip())]
    # Каждое число из счёта названо; итог по VK — единственное сложение.
    for сколько in счёт.values():
        assert сколько in числа, сколько
    assert "   ручная_правка: 1" in строки, "неизвестное не прячем"


def test_пустой_отчёт_говорит_словами():
    assert sources.свод({}) == ["   пока никого"]


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


# --- 4. Карточка: где она показывается и где не должна ----------------------

def test_карточку_отправляют_ровно_в_двух_местах():
    """Конец анкеты и команда `/music` — всё.

    Третье место означало бы, что человек получает её дважды за один
    приход, а это уже реклама, а не предложение. Сторож на это такой же,
    как у кружков знакомства: он знает места поимённо и падает на новом.
    """
    места = []
    for папка in ("handlers", "services"):
        for файл in (КОРЕНЬ / папка).rglob("*.py"):
            код = _только_код(файл.read_text(encoding="utf-8"))
            if "music . отправить" in код:
                места.append(файл.name)

    assert sorted(места) == ["music.py", "onboarding.py"], места


def test_повторный_старт_карточку_не_шлёт():
    """Вернувшемуся она не приходит: анкета у него уже позади.

    Отдельной отметки «уже показывали» для этого не нужно и заводить её
    нельзя — лишняя колонка только добавила бы способов разъехаться.
    `onboarding_completed` поднимается однажды, и второго конца анкеты у
    человека не бывает.
    """
    import inspect

    from handlers import onboarding

    старт = inspect.getsource(onboarding.cmd_start)
    assert "music" not in старт, "в /start карточке делать нечего"

    # И ветка вернувшегося обязана выходить сама, не доходя до анкеты.
    ветка = старт.split("if completed:", 1)[1].split("\n\n", 1)[0]
    assert "return" in ветка


def test_карточка_возвращается_командой():
    """Один раз — правильно. Один раз без пути назад — это «никогда»."""
    import inspect

    from handlers import music as handler
    from aiogram.filters import Command

    assert any(isinstance(ф.callback, Command) or "music" in str(ф.callback)
               for ф in handler.router.message.handlers[0].filters)
    assert "music.отправить" in inspect.getsource(handler.cmd_music)


def test_команда_музыки_не_молчит_при_выключенном_адресе(monkeypatch):
    """Молчание человек прочитает как поломку бота, а не как решение."""
    from handlers import music as handler

    monkeypatch.setattr(config, "MUSIC_URL", "")
    сказано = []

    class Чат:
        async def answer(self, text, **kwargs):
            сказано.append(text)

    asyncio.run(handler.cmd_music(Чат()))
    assert len(сказано) == 1 and сказано[0]


# --- 5. Отчёт не показывает людей -------------------------------------------

def _отчёт(session, monkeypatch, команда):
    """Прогнать настоящий `/sources` на этой сессии. Вернуть, что он сказал."""
    import contextlib

    from handlers import access as модуль

    @contextlib.asynccontextmanager
    async def своя():
        yield session

    monkeypatch.setattr(модуль, "get_session", своя)
    monkeypatch.setattr(config, "ADMIN_IDS", {ВЛАДЕЛИЦА})
    сказано = []

    class Чат:
        text = команда
        from_user = type("U", (), {"id": ВЛАДЕЛИЦА})()

        async def answer(self, текст, **kwargs):
            сказано.append(текст)

    asyncio.get_event_loop_policy()
    return сказано, Чат()


def test_в_отчёте_нет_ни_имён_ни_номеров(monkeypatch):
    """`/sources` — про числа, а не про людей.

    Проверяется не текст обработчика, а то, что он правда сказал: грепом по
    коду этого не поймать — там законно стоит `message.from_user.id` в
    проверке хозяина, и сторож падал на ней. Поэтому в базе заводятся люди
    с именами, и в готовом ответе этих имён быть не должно.
    """
    async def scenario():
        async with db() as session:
            она = await session.get(User, ОНА)
            она.full_name = "Мария Петрова"
            она.username = "mariapetrova"
            она.first_source = "instagram_profile"
            она.referral = "friend_SECRET42"
            await session.commit()

            сказано, чат = _отчёт(session, monkeypatch, "/sources")
            from handlers.access import marketing_report
            await marketing_report(чат)

            текст = "\n".join(сказано)
            assert текст, "отчёт обязан прийти"
            for личное in ("Мария", "Петрова", "mariapetrova",
                           "friend_SECRET42", str(ОНА)):
                assert личное not in текст, личное
            assert "Instagram: 1" in текст
    run(scenario)


def test_отчёт_за_семь_дней_приходит_и_называет_срок(monkeypatch):
    """`/sources 7` — это семь дней, а не тридцать и не падение."""
    async def scenario():
        async with db() as session:
            сказано, чат = _отчёт(session, monkeypatch, "/sources 7")
            from handlers.access import marketing_report
            await marketing_report(чат)

            текст = "\n".join(сказано)
            assert "за 7 дн." in текст, текст[:200]
            assert "🔗 Первый источник" in текст
    run(scenario)


def test_отчёт_чужому_не_приходит_вовсе(monkeypatch):
    """Не «нет доступа», а тишина: чужому знать о команде незачем."""
    async def scenario():
        async with db() as session:
            сказано, чат = _отчёт(session, monkeypatch, "/sources")
            чат.from_user = type("U", (), {"id": ОНА})()
            from handlers.access import marketing_report
            await marketing_report(чат)

            assert сказано == []
    run(scenario)


def test_срок_отчёта_берётся_из_команды_и_держится_в_рамках():
    """`/sources 7` — это семь дней, а `/sources 99999` не роняет выборку."""
    исходник = (КОРЕНЬ / "handlers" / "access.py").read_text(encoding="utf-8")
    кусок = исходник.split("async def marketing_report", 1)[1].split("\nasync def")[0]
    assert "isdigit()" in кусок
    assert "max(1, min(int(части[1]), 365))" in кусок


def test_отчёт_собирается_целиком_на_живых_данных():
    """Проверяем не куски, а весь ответ: он обязан собраться и сойтись."""
    async def scenario():
        async with db() as session:
            люди = {ОНА: "instagram_profile", ДРУГАЯ: "vk_a1_food"}
            for uid, метка in люди.items():
                человек = await session.get(User, uid)
                человек.first_source = метка
            владелица = await session.get(User, ВЛАДЕЛИЦА)
            владелица.first_source = "vk_profile"
            await session.commit()

            итог = await analytics.report(session, days=7,
                                          exclude={ВЛАДЕЛИЦА})
            строки = sources.свод(итог.sources)
            текст = "\n".join(строки)

            # Владелицы в отчёте нет — значит, и её площадки тоже.
            assert "VK: 1" not in текст
            assert "Instagram: 1" in текст
            assert "vk_a1_food: 1" in текст
            assert "Итого с VK (новая метка и старые): 1" in текст
    run(scenario)
