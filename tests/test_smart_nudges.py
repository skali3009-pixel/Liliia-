"""Умные подсказки целиком: от записей в базе до решения написать.

Сюда перенесены гарантии двух прежних напоминаний — про воду в 16:00 и про
пустой дневник в 20:00. Сами они удалены: бот больше не пишет по часам. Но
то, что они защищали, никуда не делось и обязано работать по-прежнему:
не писать тому, кто и так справляется; не писать выключившему напоминания;
не писать не дошедшему до конца анкеты; не догонять того, кто бросил бота.
"""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (Base, GenderEnum, GoalEnum, Meal, StepLog, User,
                    WaterLog)
from models.notification import KIND_WATER
from services import notifications

# 15:00 в Москве (UTC+3) — начало часа, когда движок и просыпается.
NOON_MSK = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
NORM_WATER = 2000


@contextlib.asynccontextmanager
async def db(**overrides):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        fields = dict(
            id=1, gender=GenderEnum.FEMALE, age=30, height_cm=165,
            current_weight_kg=62, goal=GoalEnum.LOSE_WEIGHT,
            onboarding_completed=True, timezone="Europe/Moscow",
            daily_water_ml=NORM_WATER, daily_calories=1800, daily_protein_g=90,
            reminders_enabled=True,
            # Человек был здесь вчера: иначе он «пропал», и ему пишет
            # не движок подсказок, а письмо о возвращении.
            created_at=NOON_MSK - timedelta(days=1),
        )
        fields.update(overrides)
        session.add(User(**fields))
        await session.commit()
        yield session
    await engine.dispose()


def run(scenario):
    asyncio.run(scenario())


def trace(session, *, at):
    """Любой след человека: по нему считается, пропал он или нет."""
    session.add(WaterLog(user_id=1, amount_ml=1, logged_at=at))


async def planned(session, *, now=NOON_MSK):
    return await notifications.due(session, now_utc=now)


# --- кому пишем -----------------------------------------------------------


def test_someone_who_is_behind_gets_one_message():
    async def scenario():
        async with db() as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()
            out = await planned(session)
            assert len(out) == 1
    run(scenario)


def test_water_is_what_comes_when_water_is_what_is_missing():
    """Что именно предложить, решает срез дня, а не расписание."""
    async def scenario():
        async with db() as session:
            session.add(Meal(user_id=1, name="каша", calories=1700, protein_g=88,
                             fat_g=60, carbs_g=190, logged_at=NOON_MSK))
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()
            _, push, _ = (await planned(session))[0]
            assert push.kind == KIND_WATER
            assert push.amount == 250      # добавляется прямо из чата
    run(scenario)


def test_exactly_one_message_even_when_several_things_are_behind():
    """Показать сразу три недобора — значит не показать ни одного."""
    async def scenario():
        async with db() as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()
            out = await planned(session)
            assert len(out) == 1
    run(scenario)


# --- кому молчим ----------------------------------------------------------


def test_someone_who_is_doing_fine_hears_nothing():
    """Закрытый день — повод промолчать, а не выжать ещё одно действие."""
    async def scenario():
        async with db() as session:
            session.add(WaterLog(user_id=1, amount_ml=NORM_WATER, logged_at=NOON_MSK))
            session.add(Meal(user_id=1, name="каша", calories=1800, protein_g=90,
                             fat_g=60, carbs_g=200, logged_at=NOON_MSK))
            session.add(StepLog(user_id=1, day=NOON_MSK.date(), steps=12000))
            await session.commit()
            assert await planned(session) == []
    run(scenario)


def test_unentered_steps_are_asked_for_not_assumed():
    """Шаги вносит человек. Молчать про них нельзя, а делать вывод «ты мало
    двигалась» — тем более: этих данных у бота просто нет."""
    async def scenario():
        async with db() as session:
            session.add(WaterLog(user_id=1, amount_ml=NORM_WATER, logged_at=NOON_MSK))
            session.add(Meal(user_id=1, name="каша", calories=1800, protein_g=90,
                             fat_g=60, carbs_g=200, logged_at=NOON_MSK))
            await session.commit()
            _, push, _ = (await planned(session))[0]
            assert push.code == "steps"
            assert "Здоровь" in push.text or "внес" in push.text.lower()
    run(scenario)


def test_without_a_calculated_norm_water_is_not_advised():
    """Раньше на этот случай была запасная норма в 1500 мл. Теперь нет.

    Прежнее напоминание про воду брало полтора литра, если норма почему-то
    не посчитана, — и говорило человеку цифру, которую само же и выдумало.
    Движок так не делает: чего он не знает, о том не советует. Дошедшей до
    конца анкеты норма считается всегда, так что случай этот — про сбой, а
    в сбое лучше промолчать, чем назвать выдуманное число.
    """
    async def scenario():
        async with db(daily_water_ml=None) as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()
            assert all(p.kind != KIND_WATER for _, p, _ in await planned(session))
    run(scenario)


def test_switched_off_reminders_are_really_off():
    async def scenario():
        async with db(reminders_enabled=False) as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()
            assert await planned(session) == []
    run(scenario)


def test_someone_who_never_finished_the_form_is_left_alone():
    async def scenario():
        async with db(onboarding_completed=False) as session:
            assert await planned(session) == []
    run(scenario)


def test_someone_who_disappeared_is_not_chased_with_advice():
    """Тому, кто бросил бота, «выпей воды» приходило каждый вечер.

    Это не напоминание, а преследование. Пропавшему пишет
    services/comeback.py — два раза и без единой цифры.
    """
    async def scenario():
        async with db(created_at=NOON_MSK - timedelta(days=30)) as session:
            trace(session, at=NOON_MSK - timedelta(days=20))
            await session.commit()
            assert await planned(session) == []
    run(scenario)


def test_someone_who_was_here_yesterday_still_hears_it():
    """Граница проходит по любому следу, а не по одной только воде сегодня."""
    async def scenario():
        async with db() as session:
            trace(session, at=NOON_MSK - timedelta(hours=20))
            await session.commit()
            assert len(await planned(session)) == 1
    run(scenario)


def test_the_engine_wakes_only_at_the_top_of_the_hour():
    async def scenario():
        async with db() as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()
            assert await planned(session, now=NOON_MSK + timedelta(minutes=17)) == []
    run(scenario)


def test_the_night_is_left_alone_end_to_end():
    async def scenario():
        async with db() as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()
            # 03:00 в Москве.
            night = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
            assert await planned(session, now=night) == []
    run(scenario)


def test_a_message_already_sent_today_closes_the_hour():
    async def scenario():
        async with db() as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()
            out = await planned(session)
            _, push, day = out[0]
            await notifications.remember(session, push, day=day, now_utc=NOON_MSK)
            # Следующий час: промежуток между сообщениями ещё не выдержан.
            hour_later = NOON_MSK + timedelta(hours=1)
            assert await planned(session, now=hour_later) == []
    run(scenario)


def test_someone_who_just_opened_the_app_is_left_alone():
    async def scenario():
        async with db() as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            user = await session.get(User, 1)
            user.last_app_open = NOON_MSK - timedelta(minutes=5)
            await session.commit()
            assert await planned(session) == []
    run(scenario)


def test_later_pressed_in_the_chat_is_honoured_by_the_engine():
    """«Позже» убирает именно эту тему — и не заменяет её тут же другой.

    Заменить одно предложение другим через час было бы обходом просьбы:
    человек просил тишины, а получил то же самое другими словами.
    """
    async def scenario():
        async with db() as session:
            trace(session, at=NOON_MSK - timedelta(days=1))
            await session.commit()

            _, push, day = (await planned(session))[0]
            await notifications.remember(session, push, day=day, now_utc=NOON_MSK)
            await notifications.snooze(session, 1, push.kind,
                                       until=NOON_MSK + timedelta(hours=3))

            # Через четыре часа промежуток выдержан, но тема ещё отложена.
            later = NOON_MSK + timedelta(hours=4)
            assert all(p.kind != push.kind for _, p, _ in await planned(session, now=later))
    run(scenario)


# --- формулировки ---------------------------------------------------------


def test_the_wording_changes_from_day_to_day_but_not_within_a_day():
    from services.context import VARIANTS, say

    seed = 20260908
    assert say(seed, "water_empty") == say(seed, "water_empty")
    different = {say(seed + shift, "water_empty") for shift in range(5)}
    assert len(different) > 1


def test_every_intent_has_several_ways_to_say_it():
    from services.context import VARIANTS

    for key, options in VARIANTS.items():
        assert len(options) >= 5, f"«{key}»: слишком мало формулировок"
        assert len(set(options)) == len(options), f"«{key}»: повтор"


def test_no_wording_scolds_or_promises_medicine():
    """Стиль — не украшение: «вы должны» и обещания здоровья запрещены ТЗ."""
    from services.context import VARIANTS

    forbidden = ("вы долж", "ты долж", "не забуд", "обязан", "нужно больше",
                 "отёк", "лимф", "метаболизм", "мышцы не уйдут")
    for key, options in VARIANTS.items():
        for text in options:
            low = text.lower()
            for word in forbidden:
                assert word not in low, f"«{key}»: {text}"
