"""Цифры для владельца: люди, деньги и точка окупаемости."""

import asyncio
import contextlib
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from models import ApiUsage, Base, Meal, MealTypeEnum, Payment, User, WaterLog
from services import metrics, owner_reports

OWNER = 246959020


@contextlib.asynccontextmanager
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def now():
    return datetime.now(timezone.utc)


async def add_person(session, user_id: int, *, active: bool, days_ago: int = 0,
                     onboarded: bool = True):
    session.add(User(id=user_id, onboarding_completed=onboarded,
                     created_at=now() - timedelta(days=days_ago)))
    if active:
        session.add(Meal(user_id=user_id, name="каша", calories=300,
                         protein_g=10, fat_g=5, carbs_g=50,
                         meal_type=MealTypeEnum.BREAKFAST,
                         logged_at=now() - timedelta(days=days_ago)))
    await session.commit()


# --- Люди --------------------------------------------------------------

def test_registered_and_actually_using_are_different_numbers():
    """Главная подмена в такой статистике — считать пришедших за живых."""
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=True)
            await add_person(session, 2, active=False)
            await add_person(session, 3, active=False, onboarded=False)

            people = await metrics.audience(session, days=1)
            assert people.registered == 3
            assert people.onboarded == 2
            assert people.stuck == 1          # начал анкету и бросил
            assert people.active == 1         # записал еду только один
    run(scenario)


def test_opening_the_app_is_not_using_it():
    """Активность — это запись, а не открытая страница."""
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=False)
            assert (await metrics.audience(session, days=7)).active == 0

            session.add(WaterLog(user_id=1, amount_ml=250, logged_at=now()))
            await session.commit()
            assert (await metrics.audience(session, days=7)).active == 1
    run(scenario)


def test_a_person_active_twice_is_still_one_person():
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=True)
            session.add(WaterLog(user_id=1, amount_ml=250, logged_at=now()))
            await session.commit()
            assert (await metrics.audience(session, days=1)).active == 1
    run(scenario)


def test_last_week_and_last_month_are_counted_apart():
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=True, days_ago=1)
            await add_person(session, 2, active=True, days_ago=20)

            people = await metrics.audience(session, days=7)
            assert people.active == 1
            assert people.active_30d == 2
    run(scenario)


# --- Деньги ------------------------------------------------------------

def test_revenue_counts_what_actually_reaches_the_owner(monkeypatch):
    """Звёзды — не доллары: Телеграм удерживает свою долю."""
    async def scenario():
        monkeypatch.setattr(config, "STAR_USD", 0.013)
        monkeypatch.setattr(config, "TAX_PERCENT", 0)
        async with db() as session:
            await add_person(session, 1, active=True)
            session.add(Payment(user_id=1, amount=499, days=30, paid_at=now()))
            await session.commit()

            money = await metrics.money(session, days=30)
            assert money.stars == 499
            assert money.revenue_usd == pytest.approx(6.49, abs=0.01)
            assert money.payers == 1
    run(scenario)


def test_refunded_payments_are_not_revenue():
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=True)
            session.add(Payment(user_id=1, amount=499, days=30, paid_at=now(),
                                refunded=True))
            await session.commit()
            assert (await metrics.money(session, days=30)).stars == 0
    run(scenario)


def test_cost_per_living_person_is_visible(monkeypatch):
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=True)
            await add_person(session, 2, active=True)
            session.add(ApiUsage(user_id=1, kind="photo", model="claude-sonnet-5",
                                 cost_usd=1.0, day=date.today()))
            await session.commit()

            money = await metrics.money(session, days=30)
            assert money.active == 2
            assert money.per_active_usd == pytest.approx(0.5)
    run(scenario)


def test_breakeven_says_how_many_payers_are_needed(monkeypatch):
    """Ради этой цифры отчёт и затевался."""
    async def scenario():
        monkeypatch.setattr(config, "STAR_USD", 0.013)
        monkeypatch.setattr(config, "TAX_PERCENT", 0)
        monkeypatch.setattr(config, "SUB_PRICE_STARS", 499)
        monkeypatch.setattr(config, "FIXED_COSTS_USD", 30.0)
        async with db() as session:
            await add_person(session, 1, active=True)
            session.add(ApiUsage(user_id=1, kind="photo", model="claude-sonnet-5",
                                 cost_usd=6.0, day=date.today()))
            await session.commit()

            money = await metrics.money(session, days=30)
            # Расходы 36 $, с подписки остаётся 6.49 $ → нужно шестеро.
            assert money.costs_usd == pytest.approx(36.0)
            assert money.breakeven_payers == 6
    run(scenario)


def test_tax_is_taken_off_the_subscription(monkeypatch):
    async def scenario():
        monkeypatch.setattr(config, "STAR_USD", 0.013)
        monkeypatch.setattr(config, "SUB_PRICE_STARS", 499)
        monkeypatch.setattr(config, "TAX_PERCENT", 6)
        async with db() as session:
            money = await metrics.money(session, days=30)
            assert money.per_payer_usd == pytest.approx(6.10, abs=0.01)
    run(scenario)


def test_profit_is_not_claimed_while_fixed_costs_are_unknown(monkeypatch):
    """Сервер и бухгалтерия платятся всё равно — «прибыль» без них враньё."""
    async def scenario():
        monkeypatch.setattr(config, "FIXED_COSTS_USD", 0.0)
        async with db() as session:
            money = await metrics.money(session, days=30)
            assert money.known is False
            assert "не заполнены постоянные расходы" in "\n".join(
                owner_reports._money_lines(money)
            )
    run(scenario)


# --- Тексты ------------------------------------------------------------

def test_daily_report_reads_without_a_calculator():
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=True)
            text = await owner_reports.daily(session)
            assert "Сводка за сутки" in text
            assert "Всего зарегистрировано: 1" in text
            assert "Пользовались: 1" in text
    run(scenario)


def test_weekly_report_shows_what_to_charge_for():
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=True)
            session.add(ApiUsage(user_id=1, kind="photo", model="claude-sonnet-5",
                                 cost_usd=0.5, day=date.today()))
            await session.commit()

            text = await owner_reports.weekly(session)
            assert "Неделя целиком" in text
            assert "Чем пользуются" in text
            assert "Фото:" in text
    run(scenario)


def test_reports_never_show_names_or_diaries():
    """Владельцу нужны цифры, а не чужие дневники."""
    async def scenario():
        async with db() as session:
            session.add(User(id=1, onboarding_completed=True, full_name="Мария Петрова"))
            await session.commit()
            session.add(Meal(user_id=1, name="секретный борщ", calories=300,
                             protein_g=10, fat_g=5, carbs_g=50,
                             meal_type=MealTypeEnum.LUNCH, logged_at=now()))
            await session.commit()

            for text in (await owner_reports.daily(session),
                         await owner_reports.weekly(session)):
                assert "Мария" not in text
                assert "борщ" not in text
    run(scenario)


# --- Расписание --------------------------------------------------------

def test_reports_come_by_the_owners_clock():
    """9:00 в Москве — это не 9:00 UTC."""
    moment = datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc)   # 09:00 в Москве
    assert metrics.is_time_for("Europe/Moscow", time(9, 0), moment=moment)
    assert not metrics.is_time_for("Europe/London", time(9, 0), moment=moment)


def test_weekly_report_only_on_friday():
    friday = datetime(2026, 9, 11, 17, 0, tzinfo=timezone.utc)   # пятница 20:00 МСК
    saturday = friday + timedelta(days=1)
    assert metrics.is_time_for("Europe/Moscow", time(20, 0), moment=friday, weekday=4)
    assert not metrics.is_time_for("Europe/Moscow", time(20, 0), moment=saturday, weekday=4)


def test_owner_timezone_comes_from_the_owners_profile(monkeypatch):
    async def scenario():
        monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
        async with db() as session:
            session.add(User(id=OWNER, timezone="Asia/Novosibirsk"))
            await session.commit()
            assert await metrics.owner_timezone(session) == "Asia/Novosibirsk"
    run(scenario)


def test_moscow_is_the_fallback(monkeypatch):
    async def scenario():
        monkeypatch.setattr(config, "ADMIN_IDS", set())
        async with db() as session:
            assert await metrics.owner_timezone(session) == "Europe/Moscow"
    run(scenario)


def test_daily_numbers_do_not_borrow_from_yesterday():
    """«За сутки» — это последние 24 часа, а не «сегодня и кусок вчера»."""
    async def scenario():
        async with db() as session:
            await add_person(session, 1, active=True)
            for hours in (2, 30, 26 * 24):        # сегодня, вчера, месяц назад
                session.add(ApiUsage(user_id=1, kind="photo",
                                     model="claude-sonnet-5", cost_usd=0.01,
                                     day=date.today(),
                                     created_at=now() - timedelta(hours=hours)))
            await session.commit()

            assert (await metrics.activity(session, days=1)).photos == 1
            assert (await metrics.activity(session, days=7)).photos == 2
            assert (await metrics.activity(session, days=30)).photos == 3
    run(scenario)


def test_daily_report_answers_the_money_question_too(monkeypatch):
    """Сходится ли подписка с расходами — видно каждый день, не раз в неделю."""
    async def scenario():
        monkeypatch.setattr(config, "FIXED_COSTS_USD", 12.0)
        monkeypatch.setattr(config, "STAR_USD", 0.013)
        monkeypatch.setattr(config, "TAX_PERCENT", 0)
        async with db() as session:
            await add_person(session, 1, active=True)
            text = await owner_reports.daily(session)
            assert "За 30 дней" in text
            assert "Чтобы окупалось, нужно" in text
    run(scenario)
