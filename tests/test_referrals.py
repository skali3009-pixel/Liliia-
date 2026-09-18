"""Приглашения с наградой.

Проверяется здесь не «начисляются ли дни» — это самая простая часть, — а три
вещи, каждая из которых молча превращает награду в дыру в кассе.

Первая: пока оплата выключена, не должно начисляться ничего и, главное, не
должно **отмечаться** начисленным. Отметка без выдачи — это тихая потеря:
день, когда оплату включат, все накопившиеся награды окажутся «уже выданными».

Вторая: бесплатное действие не может приносить неограниченную награду. Нажать
«Начать» стоит одно касание, и без потолка десять знакомых превращаются в два
месяца доступа.

Третья: наградить дважды за одно и то же нельзя ни одним путём.
"""

import asyncio
import contextlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from models import (Base, Payment, Referral, Subscription, SubscriptionSource,
                    User)
from services import friends, referrals
from services.subscriptions import check_access

ANNA, MARIA, OLGA = 201, 202, 203


@contextlib.asynccontextmanager
async def db(*, completed=(ANNA,)):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        for uid, name in ((ANNA, "Анна Петрова"), (MARIA, "Мария Иванова"),
                          (OLGA, "Ольга Смирнова")):
            session.add(User(id=uid, full_name=name,
                             onboarding_completed=uid in completed))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


@pytest.fixture
def paid(monkeypatch):
    """Оплата включена — награды работают."""
    monkeypatch.setattr(config, "PAYWALL", True)
    monkeypatch.setattr(config, "ADMIN_IDS", [])


@pytest.fixture
def free(monkeypatch):
    """Оплата выключена — так бот живёт сегодня."""
    monkeypatch.setattr(config, "PAYWALL", False)
    monkeypatch.setattr(config, "ADMIN_IDS", [])


async def _link_of(session, user_id: int) -> str:
    """Аргумент ссылки этого человека — то, что придёт в /start."""
    code = await friends.invite_code(session, user_id)
    return f"{friends.INVITE_PREFIX}{code}"


async def _days_left(session, user_id: int) -> int:
    return (await check_access(session, user_id)).days_left


# --- Кто кого привёл ------------------------------------------------------

def test_переход_по_ссылке_записывается():
    async def scenario():
        async with db() as session:
            args = await _link_of(session, ANNA)
            assert await referrals.remember(session, MARIA, args) is True

            row = (await session.execute(
                select(Referral).where(Referral.invited_id == MARIA)
            )).scalar_one()
            assert row.inviter_id == ANNA
            assert row.signup_rewarded_at is None
    run(scenario)


def test_старожила_привести_нельзя():
    """Две подруги обменялись ссылками — это не приглашение, а вторая касса."""
    async def scenario():
        async with db(completed=(ANNA, MARIA)) as session:
            args = await _link_of(session, ANNA)
            assert await referrals.remember(session, MARIA, args) is False
            assert (await session.execute(select(Referral))).first() is None
    run(scenario)


def test_себя_привести_нельзя():
    async def scenario():
        async with db(completed=()) as session:
            args = await _link_of(session, ANNA)
            assert await referrals.remember(session, ANNA, args) is False
    run(scenario)


def test_привели_один_раз_и_навсегда():
    """Второй ссылкой награду на себя не перевесить."""
    async def scenario():
        async with db(completed=()) as session:
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))
            assert await referrals.remember(
                session, MARIA, await _link_of(session, OLGA)) is False

            row = (await session.execute(
                select(Referral).where(Referral.invited_id == MARIA)
            )).scalar_one()
            assert row.inviter_id == ANNA
    run(scenario)


def test_обычная_ссылка_ничего_не_записывает():
    async def scenario():
        async with db(completed=()) as session:
            for args in (None, "", "team_XYZ", "instagram"):
                assert await referrals.remember(session, MARIA, args) is False
    run(scenario)


# --- Пока оплата выключена ------------------------------------------------

def test_без_оплаты_не_начисляется_ничего(free):
    async def scenario():
        async with db(completed=()) as session:
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))
            assert await referrals.reward_signup(session, MARIA) == (0, 0, 0)
            assert await referrals.reward_payment(session, MARIA) == (0, 0)
    run(scenario)


def test_без_оплаты_награда_не_помечается_выданной(free):
    """Отметка без выдачи сожгла бы награду: включат оплату — а платить уже «не за что»."""
    async def scenario():
        async with db(completed=()) as session:
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))
            await referrals.reward_signup(session, MARIA)
            await referrals.reward_payment(session, MARIA)

            row = (await session.execute(
                select(Referral).where(Referral.invited_id == MARIA)
            )).scalar_one()
            assert row.signup_rewarded_at is None
            assert row.payment_rewarded_at is None
    run(scenario)


# --- Награда за анкету ----------------------------------------------------

def test_за_анкету_дни_обеим(paid):
    async def scenario():
        async with db(completed=()) as session:
            session.add_all([
                Subscription(user_id=ANNA, expires_at=referrals.now()),
                Subscription(user_id=MARIA, expires_at=referrals.now()),
            ])
            await session.commit()
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))

            кто, ей, мне = await referrals.reward_signup(session, MARIA)
            assert (кто, ей, мне) == (ANNA, referrals.SIGNUP_DAYS_INVITER,
                                      referrals.SIGNUP_DAYS_NEWCOMER)
            assert await _days_left(session, ANNA) == referrals.SIGNUP_DAYS_INVITER
            assert await _days_left(session, MARIA) == referrals.SIGNUP_DAYS_NEWCOMER
    run(scenario)


def test_за_анкету_платят_один_раз(paid):
    async def scenario():
        async with db(completed=()) as session:
            session.add(Subscription(user_id=ANNA, expires_at=referrals.now()))
            await session.commit()
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))

            await referrals.reward_signup(session, MARIA)
            снова = await referrals.reward_signup(session, MARIA)
            assert снова == (0, 0, 0)
            assert await _days_left(session, ANNA) == referrals.SIGNUP_DAYS_INVITER
    run(scenario)


def test_у_награды_за_анкету_есть_потолок(paid):
    """Регистрация бесплатна, значит и награда за неё не может быть бесконечной."""
    async def scenario():
        async with db(completed=()) as session:
            session.add(Subscription(user_id=ANNA, expires_at=referrals.now()))
            await session.commit()
            args = await _link_of(session, ANNA)

            # Приводим на одну подругу больше, чем разрешено: последняя
            # обязана не принести ничего.
            for номер in range(referrals.SIGNUP_LIMIT + 1):
                uid = 1000 + номер
                session.add(User(id=uid, full_name=f"Гостья {номер}"))
                await session.commit()
                await referrals.remember(session, uid, args)
                _, ей, _ = await referrals.reward_signup(session, uid)
                ожидаем = (referrals.SIGNUP_DAYS_INVITER
                           if номер < referrals.SIGNUP_LIMIT else 0)
                assert ей == ожидаем, номер

            assert await _days_left(session, ANNA) == (
                referrals.SIGNUP_LIMIT * referrals.SIGNUP_DAYS_INVITER)
    run(scenario)


# --- Награда за оплату ----------------------------------------------------

def test_за_оплату_дни_приглашающей(paid):
    async def scenario():
        async with db(completed=()) as session:
            session.add(Subscription(user_id=ANNA, expires_at=referrals.now()))
            await session.commit()
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))

            assert await referrals.reward_payment(session, MARIA) == (
                ANNA, referrals.PAYMENT_DAYS_INVITER)
            assert await _days_left(session, ANNA) == referrals.PAYMENT_DAYS_INVITER
    run(scenario)


def test_за_оплату_платят_один_раз_за_человека(paid):
    """Продление — не новая награда: платим за приведённого, а не процент с платежей."""
    async def scenario():
        async with db(completed=()) as session:
            session.add(Subscription(user_id=ANNA, expires_at=referrals.now()))
            await session.commit()
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))

            await referrals.reward_payment(session, MARIA)
            assert await referrals.reward_payment(session, MARIA) == (0, 0)
            assert await _days_left(session, ANNA) == referrals.PAYMENT_DAYS_INVITER
    run(scenario)


def test_у_награды_за_оплату_потолка_нет(paid):
    """Она выдаётся из уже пришедших денег — ограничивать её нечем."""
    async def scenario():
        async with db(completed=()) as session:
            session.add(Subscription(user_id=ANNA, expires_at=referrals.now()))
            await session.commit()
            args = await _link_of(session, ANNA)

            сколько = referrals.SIGNUP_LIMIT + 3
            for номер in range(сколько):
                uid = 2000 + номер
                session.add(User(id=uid, full_name=f"Гостья {номер}"))
                await session.commit()
                await referrals.remember(session, uid, args)
                _, дней = await referrals.reward_payment(session, uid)
                assert дней == referrals.PAYMENT_DAYS_INVITER, номер

            assert await _days_left(session, ANNA) == (
                сколько * referrals.PAYMENT_DAYS_INVITER)
    run(scenario)


# --- Кому дни не нужны ----------------------------------------------------

def test_бесплатному_навсегда_дни_не_дарят(paid):
    """Ему они не добавляют ничего, а сообщение «тебе неделя в подарок» — неправда."""
    async def scenario():
        async with db(completed=()) as session:
            session.add(Subscription(user_id=ANNA, expires_at=referrals.now(),
                                     lifetime=True))
            session.add(Subscription(user_id=MARIA, expires_at=referrals.now()))
            await session.commit()
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))

            кто, ей, мне = await referrals.reward_signup(session, MARIA)
            assert (кто, ей) == (ANNA, 0)
            assert мне == referrals.SIGNUP_DAYS_NEWCOMER
    run(scenario)


def test_владельцу_дни_не_дарят(paid, monkeypatch):
    async def scenario():
        monkeypatch.setattr(config, "ADMIN_IDS", [ANNA])
        async with db(completed=()) as session:
            session.add(Subscription(user_id=MARIA, expires_at=referrals.now()))
            await session.commit()
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))
            _, ей, _ = await referrals.reward_signup(session, MARIA)
            assert ей == 0
    run(scenario)


# --- Сводка ---------------------------------------------------------------

def test_сводка_считает_людей_а_не_отметки(free):
    """При выключенной оплате отметок нет вовсе — а подруги уже пришли."""
    async def scenario():
        async with db(completed=()) as session:
            args = await _link_of(session, ANNA)
            for uid in (MARIA, OLGA):
                await referrals.remember(session, uid, args)

            гостья = await session.get(User, MARIA)
            гостья.onboarding_completed = True
            session.add(Payment(user_id=MARIA, amount=499, days=30))
            await session.commit()

            итог = await referrals.summary(session, ANNA)
            assert (итог.invited, итог.signed_up, итог.paid) == (2, 1, 1)
            assert итог.days_earned == 0
            assert итог.signups_left == referrals.SIGNUP_LIMIT
    run(scenario)


# --- Удаление данных ------------------------------------------------------

def test_удаление_уносит_и_то_где_человек_приглашающий():
    """Приведённого заберёт каскад, а номер приглашающей внешним ключом не защищён."""
    from services import deletion

    async def scenario():
        async with db(completed=()) as session:
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))
            assert await deletion.purge(session, ANNA) is True
            assert (await session.execute(select(Referral))).first() is None
    run(scenario)


def test_удаление_приведённой_не_трогает_чужую_историю():
    async def scenario():
        async with db(completed=()) as session:
            await referrals.remember(session, MARIA, await _link_of(session, ANNA))
            await referrals.remember(session, OLGA, await _link_of(session, ANNA))
            from services import deletion

            await deletion.purge(session, MARIA)
            остались = list((await session.execute(select(Referral))).scalars())
            assert [r.invited_id for r in остались] == [OLGA]
    run(scenario)


# --- Команда /referral ----------------------------------------------------

class ФейковоеСообщение:
    """Сообщение, которое запоминает отправленное."""

    def __init__(self, user_id=ANNA):
        self.отправлено = []
        self.from_user = type("U", (), {"id": user_id, "full_name": "Анна"})()

    async def answer(self, текст, **_):
        self.отправлено.append(текст)


def test_команда_доступна_когда_доступ_уже_закрыт():
    """Приглашение — единственный способ вернуть доступ, не заплатив.

    Убери /referral из списка открытых — и человек с истёкшим сроком увидит
    вместо ссылки предложение купить подписку. То есть дверь, которую мы сами
    ему нарисовали, окажется заперта.
    """
    from middlewares.access import OPEN_COMMANDS

    assert "/referral" in OPEN_COMMANDS


def test_без_оплаты_в_ответе_нет_обещаний_про_дни(free, monkeypatch):
    """Обещать подарок, которым нельзя воспользоваться, хуже, чем молчать."""
    from handlers import access as access_handlers

    async def scenario():
        async with db(completed=()) as session:
            await friends.invite_code(session, ANNA)

            import db as db_module
            monkeypatch.setattr(db_module, "get_session",
                                lambda: _same(session))
            monkeypatch.setattr(access_handlers, "get_session",
                                lambda: _same(session))
            monkeypatch.setattr(config, "BOT_USERNAME", "aura_bot")

            сообщение = ФейковоеСообщение()
            await access_handlers.my_invite_link(сообщение)

            ответ = "\n".join(сообщение.отправлено)
            assert "https://t.me/aura_bot?start=friend_" in ответ
            for слово in ("день", "дня", "дней", "подар"):
                assert слово not in ответ.lower(), слово
    run(scenario)


@contextlib.asynccontextmanager
async def _same(session):
    """Подменяет get_session уже открытой сессией теста."""
    yield session


# --- Механика подключена, а не лежит рядом --------------------------------

def test_награды_вызываются_из_бота():
    """Служба, которую никто не зовёт, — это не механика, а файл.

    Оба места названы поимённо: анкета и оплата. Если однажды награду
    перенесут, пусть тест упадёт и заставит перечитать, куда именно.
    """
    from pathlib import Path

    корень = Path(__file__).resolve().parent.parent
    анкета = (корень / "handlers" / "onboarding.py").read_text(encoding="utf-8")
    оплата = (корень / "handlers" / "access.py").read_text(encoding="utf-8")

    assert "referrals.remember(" in анкета
    assert "referrals.reward_signup(" in анкета
    assert "referrals.reward_payment(" in оплата

    # И нигде больше: третье место начисления — это второй счёт тех же дней.
    все = [ф for ф in корень.rglob("*.py")
           if not str(ф.relative_to(корень)).startswith(("tests/", "promo/"))]
    зовут = [str(ф.relative_to(корень)) for ф in все
             if "reward_signup(" in ф.read_text(encoding="utf-8")
             or "reward_payment(" in ф.read_text(encoding="utf-8")]
    assert sorted(зовут) == ["handlers/access.py", "handlers/onboarding.py",
                             "services/referrals.py"], зовут
