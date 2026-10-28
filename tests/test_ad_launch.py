"""Запуск платной рекламы: метки каналов, отчёт по ним и дожим неоплативших.

Проверяются поломки, которые молчат: метка, которую бот не узнал, письмо,
которое отсекла проверка доступа, повтор после перезапуска и рассылка тем,
кому её никто не обещал.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

import config
import scheduler
from handlers import onboarding as O
from handlers import tariffs
from models import (MarketingEvent, Payment, PlategaOrder, Subscription,
                    SubscriptionSource, SubscriptionStatus, User)
from services import analytics, pay_nudges, platega, sources
from tests.test_onboarding_flow import ОНА as UID, стенд as database

MSK = timezone(timedelta(hours=3))


# --- метки каналов ---------------------------------------------------------

def test_every_ad_mark_is_recognised_named_and_fits_the_column():
    assert len(sources.ADS) == 5
    for метка in sources.ADS:
        assert sources.recognise(метка) == метка
        assert метка in sources.НАЗВАНИЯ
        assert len(метка) <= 32          # колонка first_source — 32 знака
        assert метка not in sources.PLATFORMS and метка not in sources.LEGACY


def test_unknown_channel_mark_is_still_not_a_source():
    assert sources.recognise("tg_somebody_else") is None
    assert sources.recognise("friend_ABC") is None


def test_ad_mark_sets_first_source_for_new_user_only():
    new, old = SimpleNamespace(first_source=None, last_source=None), \
        SimpleNamespace(first_source=None, last_source=None)
    sources.apply(new, "tg_pp_legko", is_new=True)
    sources.apply(old, "tg_pp_legko", is_new=False)
    assert new.first_source == "tg_pp_legko"
    assert old.first_source == sources.EXISTING and old.last_source == "tg_pp_legko"


def test_report_shows_ads_as_their_own_block_not_as_stray_marks():
    строки = "\n".join(sources.свод({"tg_pp_legko": 4, "tg_iherb": 1, "instagram_profile": 2}))
    assert "Платная реклама" in строки
    assert "ПП ЛЕГКО И ВКУСНО: 4" in строки and "iHerb: 1" in строки
    assert "tg_pp_legko" not in строки   # машинное слово человеку не показываем


def test_ad_funnel_lines_show_arrived_done_paid_and_skip_silent_channels():
    строки = sources.воронка_рекламы({"tg_pp_legko": 10, "tg_hudeem": 0},
                                     {"tg_pp_legko": 6}, {"tg_pp_legko": 1})
    assert строки == ["   Реклама: ПП ЛЕГКО И ВКУСНО: пришло 10 · анкета 6 · оплатили 1"]
    assert sources.воронка_рекламы({}, {}, {}) == ["   пока никого"]


def test_ad_links_are_built_by_the_one_door(monkeypatch):
    monkeypatch.setattr("services.identity.config.BOT_USERNAME", "aura_scalia_bot")
    ссылки = dict(sources.ссылки_рекламы())
    assert ссылки["Реклама: ПП ЛЕГКО И ВКУСНО"] == "https://t.me/aura_scalia_bot?start=tg_pp_legko"


def test_report_counts_done_and_paid_per_source_and_ignores_refunds(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            async with maker() as s:
                for uid, done, paid, refunded in ((1, True, True, False), (2, True, False, False),
                                                  (3, False, False, False), (4, True, True, True)):
                    s.add(User(id=uid, first_source="tg_pp_legko", onboarding_completed=done))
                    if paid:
                        s.add(Payment(user_id=uid, amount=490, currency="RUB", days=30,
                                      charge_id=f"x{uid}", refunded=refunded))
                await s.commit()
                итог = await analytics.report(s, days=30)
            assert итог.sources["tg_pp_legko"] == 4
            assert итог.sources_done["tg_pp_legko"] == 3
            assert итог.sources_paid["tg_pp_legko"] == 1       # возврат человека не делает платящим
    asyncio.run(scenario())


# --- дожим -----------------------------------------------------------------

DAY0 = date(2026, 10, 30)


def _at(day, hour_msk):
    return datetime(day.year, day.month, day.day, hour_msk, 0, tzinfo=MSK).astimezone(timezone.utc)


async def _unpaid(maker, *, consent=True, completed=DAY0, uid=UID):
    async with maker() as s:
        user = await s.get(User, uid)
        user.onboarding_completed = True
        user.legal_accepted_at = datetime.now(timezone.utc)
        user.marketing_consent = consent
        user.age = 30
        user.timezone = "Europe/Moscow"
        user.daily_calories, user.daily_water_ml = 1650, 2100
        s.add(Subscription(user_id=uid, status=SubscriptionStatus.EXPIRED,
                           source=SubscriptionSource.TRIAL, expires_at=datetime.now(timezone.utc)))
        if completed:
            s.add(MarketingEvent(user_id=uid, event=analytics.PROFILE_COMPLETED,
                                 kind="", day=completed, count=1))
        await s.commit()


@pytest.fixture(autouse=True)
def _selling(monkeypatch):
    monkeypatch.setattr(config, "PAYWALL", True)
    monkeypatch.setattr(config, "ADMIN_IDS", [999999])
    monkeypatch.setattr(platega, "enabled", lambda *a, **k: True)


async def _due(maker, moment):
    async with maker() as s:
        return await pay_nudges.due(s, now_utc=moment)


def test_sequence_goes_day1_day3_day7_once_each_and_then_stops(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            plan = [(date(2026, 10, 31), "d1"), (date(2026, 11, 2), "d3"), (date(2026, 11, 6), "d7")]
            for day, kind in plan:
                got = await _due(maker, _at(day, 13))
                assert [n.kind for n in got] == [kind], day
                if kind != "d7":       # последнее письмо без цены: просто прощание
                    assert "490" in got[0].text
                async with maker() as s:
                    await pay_nudges.mark(s, got[0], day=day)
                    await s.commit()
                assert await _due(maker, _at(day, 15)) == []          # в тот же день — ничего
            assert await _due(maker, _at(date(2026, 11, 20), 13)) == []  # дальше писем нет
    asyncio.run(scenario())


def test_no_letters_outside_the_afternoon_window_or_without_consent(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker, consent=False)
            assert await _due(maker, _at(date(2026, 10, 31), 13)) == []
    asyncio.run(scenario())

    async def night():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            assert await _due(maker, _at(date(2026, 10, 31), 3)) == []
            assert await _due(maker, _at(date(2026, 10, 31), 22)) == []
    asyncio.run(night())


def test_late_letter_expires_instead_of_arriving_stale(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            # День 4 — опоздание на сутки, письмо ещё уходит; день 5 — уже поздно.
            assert [n.kind for n in await _due(maker, _at(date(2026, 11, 3), 13))] == ["d3"]
            assert await _due(maker, _at(date(2026, 11, 4), 13)) == []
    asyncio.run(scenario())


def test_people_who_finished_before_start_date_get_nothing(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker, completed=date(2026, 10, 20))
            for day in (date(2026, 10, 21), date(2026, 10, 23), date(2026, 10, 27)):
                assert await _due(maker, _at(day, 13)) == []
            await _unpaid_none(maker)
    asyncio.run(scenario())


async def _unpaid_none(maker):
    # Анкета без записи о дне завершения (заведена до учёта) — тоже тишина.
    async with maker() as s:
        s.add(User(id=777, onboarding_completed=True, legal_accepted_at=datetime.now(timezone.utc),
                   marketing_consent=True, age=30, timezone="Europe/Moscow"))
        s.add(Subscription(user_id=777, status=SubscriptionStatus.EXPIRED,
                           source=SubscriptionSource.TRIAL, expires_at=datetime.now(timezone.utc)))
        await s.commit()
    assert [n for n in await _due(maker, _at(date(2026, 10, 31), 13)) if n.user_id == 777] == []


def test_paid_owner_and_minor_get_nothing(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            async with maker() as s:
                sub = (await s.execute(select(Subscription))).scalar_one()
                sub.status, sub.source = SubscriptionStatus.ACTIVE, SubscriptionSource.PLATEGA
                sub.expires_at = datetime.now(timezone.utc) + timedelta(days=20)
                await s.commit()
            assert await _due(maker, _at(date(2026, 10, 31), 13)) == []   # оплатил
    asyncio.run(scenario())

    async def minor():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            async with maker() as s:
                (await s.get(User, UID)).age = 16
                await s.commit()
            assert await _due(maker, _at(date(2026, 10, 31), 13)) == []
    asyncio.run(minor())


def test_nothing_is_sent_while_selling_is_off(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            monkeypatch.setattr(config, "PAYWALL", False)
            assert await _due(maker, _at(date(2026, 10, 31), 13)) == []
            monkeypatch.setattr(config, "PAYWALL", True)
            monkeypatch.setattr(platega, "enabled", lambda *a, **k: False)
            assert await _due(maker, _at(date(2026, 10, 31), 13)) == []
    asyncio.run(scenario())


def test_abandoned_checkout_is_reminded_once_even_without_marketing_consent(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker, consent=False, completed=None)
            created = _at(date(2026, 10, 31), 10)
            async with maker() as s:
                s.add(PlategaOrder(id="o1", user_id=UID, status="PENDING",
                                   url="https://pay.platega.io/x", created_at=created))
                await s.commit()
            assert await _due(maker, created + timedelta(minutes=10)) == []      # ещё думает
            got = await _due(maker, created + timedelta(hours=1))
            assert [(n.kind, n.order_id) for n in got] == [("cart", "o1")]
            async with maker() as s:
                await pay_nudges.mark(s, got[0], day=date(2026, 10, 31))
                await s.commit()
            assert await _due(maker, created + timedelta(hours=3)) == []         # второго раза нет
            assert await _due(maker, created + timedelta(days=2)) == []          # и сутки прошли
    asyncio.run(scenario())


def test_stale_pending_order_is_not_nagged_and_paid_order_is_not_a_cart(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker, consent=False, completed=None)
            old = _at(date(2026, 10, 30), 10)
            async with maker() as s:
                s.add(PlategaOrder(id="old", user_id=UID, status="PENDING",
                                   url="https://pay.platega.io/x", created_at=old))
                s.add(PlategaOrder(id="done", user_id=UID, status="CONFIRMED",
                                   url="https://pay.platega.io/y", created_at=old))
                await s.commit()
            assert await _due(maker, old + timedelta(days=3)) == []
    asyncio.run(scenario())


def test_texts_do_not_guess_gender_or_invent_urgency():
    user = SimpleNamespace(full_name="Лилия Скалий", daily_calories=1650, daily_water_ml=2100)
    for kind in ("d1", "d3", "d7", "cart"):
        text = pay_nudges.render(kind, user).lower()
        for bad in ("сама", "готова", "должна", "последний день", "скидк", "успей",
                    "осталось мест", "только сегодня"):
            assert bad not in text, (kind, bad)
    assert "1650 ккал" in pay_nudges.render("d1", user)
    assert pay_nudges.render("d1", SimpleNamespace(full_name=None, daily_calories=None,
                                                   daily_water_ml=None)).startswith("🐆 твой план")


def test_every_letter_has_a_way_out_except_the_cart_reminder():
    for kind in ("d1", "d3", "d7"):
        data = [b.callback_data for row in
                pay_nudges.keyboard(pay_nudges.Nudge(1, kind, "")).inline_keyboard for b in row]
        assert pay_nudges.CB_STOP in data and "platega:buy" in data


def test_stop_button_withdraws_marketing_consent(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            monkeypatch.setattr(tariffs, "get_session", O.get_session)
            answers = []

            class Click:
                data = pay_nudges.CB_STOP
                from_user = SimpleNamespace(id=UID)

                async def answer(self, *a, **k):
                    answers.append(a)

            await tariffs.stop_pay_nudges(Click())
            async with maker() as s:
                assert (await s.get(User, UID)).marketing_consent is False
            assert answers
            assert await _due(maker, _at(date(2026, 10, 31), 13)) == []
    asyncio.run(scenario())


def test_stop_button_is_reachable_without_access(monkeypatch):
    from middlewares.access import _is_open
    from aiogram.types import CallbackQuery
    event = CallbackQuery.model_construct(data=pay_nudges.CB_STOP)
    assert _is_open(event)


# --- планировщик -----------------------------------------------------------

def test_scheduler_sends_each_letter_once_and_remembers_across_restart(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            monkeypatch.setattr(scheduler, "get_session", O.get_session)
            fixed = _at(date(2026, 10, 31), 13)
            real_due = pay_nudges.due

            async def due_at(session, **k):
                return await real_due(session, now_utc=fixed)

            monkeypatch.setattr(pay_nudges, "due", due_at)
            real_mark = pay_nudges.mark

            async def mark_at(session, nudge, **k):
                await real_mark(session, nudge, day=date(2026, 10, 31))

            monkeypatch.setattr(pay_nudges, "mark", mark_at)
            scheduler._already_sent.clear()
            bot = AsyncMock()
            await scheduler.send_pay_nudges(bot)
            await scheduler.send_pay_nudges(bot)
            bot.send_message.assert_awaited_once()
            # Перезапуск: память процесса пуста, но журнал в базе помнит.
            scheduler._already_sent.clear()
            await scheduler.send_pay_nudges(bot)
            bot.send_message.assert_awaited_once()
            async with maker() as s:
                rows = (await s.execute(select(MarketingEvent).where(
                    MarketingEvent.event == pay_nudges.EVENT))).scalars().all()
            assert [(r.user_id, r.kind) for r in rows] == [(UID, "d1")]
    asyncio.run(scenario())


def test_blocked_bot_is_marked_so_it_is_not_retried_every_ten_minutes(monkeypatch):
    from aiogram.exceptions import TelegramForbiddenError

    async def scenario():
        async with database(monkeypatch) as maker:
            await _unpaid(maker)
            monkeypatch.setattr(scheduler, "get_session", O.get_session)
            fixed = _at(date(2026, 10, 31), 13)
            real_due = pay_nudges.due

            async def due_at(session, **k):
                return await real_due(session, now_utc=fixed)

            monkeypatch.setattr(pay_nudges, "due", due_at)
            scheduler._already_sent.clear()
            bot = AsyncMock()
            bot.send_message.side_effect = TelegramForbiddenError(method=None, message="blocked")
            await scheduler.send_pay_nudges(bot)
            async with maker() as s:
                rows = (await s.execute(select(MarketingEvent).where(
                    MarketingEvent.event == pay_nudges.EVENT))).scalars().all()
            assert len(rows) == 1
    asyncio.run(scenario())


def test_unfinished_questionnaire_letter_is_not_cut_off_by_the_paywall(monkeypatch):
    """Без оплаты доступа нет по определению; письмо звало именно этих людей."""
    async def scenario():
        async with database(monkeypatch):
            monkeypatch.setattr(scheduler, "get_session", O.get_session)
            assert not await scheduler.product_messages_allowed(UID)
            assert await scheduler.funnel_messages_allowed(UID)
            monkeypatch.setattr(scheduler.unfinished, "due",
                                AsyncMock(return_value=[SimpleNamespace(user_id=UID, text="t")]))
            scheduler._already_sent.clear()
            bot = AsyncMock()
            await scheduler.send_unfinished(bot)
            bot.send_message.assert_awaited_once()
    asyncio.run(scenario())


def test_pitch_after_the_questionnaire_uses_the_persons_own_numbers():
    from handlers.access import pitch_text
    user = SimpleNamespace(full_name="Анна Иванова", daily_calories=1800, daily_water_ml=2000)
    text = pitch_text(user)
    assert text.startswith("✨ Анна, твой план") and "1800 ккал" in text and "490 ₽" in text
    assert "автосписаний нет" in text.lower()
    bare = pitch_text(SimpleNamespace(full_name=None, daily_calories=None, daily_water_ml=None))
    assert bare.startswith("✨ Твой план") and "ккал" not in bare
