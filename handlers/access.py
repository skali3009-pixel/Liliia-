"""Платный доступ: экран подписки, оплата звёздами и продление.

Оплата идёт звёздами Telegram: они не требуют ни юрлица, ни договора с
банком, и Telegram сам списывает следующий месяц, пока человек не отменит
подписку. Отмена — тоже на его стороне, в настройках Telegram.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import get_session
from models import SubscriptionSource
from services import analytics, friends, referrals
from services.step_sync import plural
from services.subscriptions import Access, activate, check_access, grant_lifetime, stats

logger = logging.getLogger(__name__)
router = Router(name="access")

CB_BUY = "sub:buy"
PAYLOAD_PREFIX = "sub_month"

# Период списания задаётся в секундах и у Telegram может быть только месячным.
MONTH_SECONDS = 30 * 24 * 60 * 60

# Как владелец может написать «без срока» в команде /grant.
FOREVER_WORDS = {"навсегда", "вечно", "forever"}


def paywall_text(access: Access) -> str:
    """Что показать человеку без доступа."""
    if access.status.value == "trial":
        return (
            "🔒 Пробный период закончился\n\n"
            "Дневник, распознавание еды по фото и голосу, тренировки, замеры и "
            "прогресс — всё остаётся на месте и включится сразу после оплаты.\n\n"
            f"Подписка — {config.SUB_PRICE_STARS} ⭐ в месяц, "
            "списывается автоматически. Отменить можно в любой момент в настройках Telegram."
        )
    return (
        "🔒 Доступ закрыт\n\n"
        "Твои записи никуда не делись — они ждут тебя.\n\n"
        f"Подписка — {config.SUB_PRICE_STARS} ⭐ в месяц. "
        "Списывается автоматически, отменить можно в любой момент."
    )


def buy_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⭐ Оформить за {config.SUB_PRICE_STARS} в месяц", callback_data=CB_BUY)
    return builder.as_markup()


async def send_paywall(message: Message, access: Access) -> None:
    await message.answer(paywall_text(access), reply_markup=buy_keyboard())


@router.message(Command("subscription"))
async def show_subscription(message: Message) -> None:
    """Состояние подписки: сколько осталось и как продлить."""
    async with get_session() as session:
        access = await check_access(session, message.from_user.id)

    if access.is_admin:
        await message.answer("Ты владелец — доступ всегда открыт.")
        return

    if not access.allowed:
        await send_paywall(message, access)
        return

    if access.is_lifetime:
        await message.answer(
            "Доступ у тебя бесплатный и бессрочный — ты пользовалась ботом "
            "ещё до того, как он стал платным. Платить не нужно, ничего не "
            "закончится."
        )
        return

    left = access.days_left
    tail = "день" if left % 10 == 1 and left % 100 != 11 else (
        "дня" if left % 10 in (2, 3, 4) and left % 100 not in (12, 13, 14) else "дней"
    )
    kind = "Пробный период" if access.is_trial else "Подписка"
    renew = (
        "Продлевается автоматически."
        if access.is_recurring
        else "Автопродления нет — оформи, чтобы не прерывалось."
    )

    await message.answer(
        f"{kind}: осталось {left} {tail}.\n{renew}",
        reply_markup=None if access.is_recurring else buy_keyboard(),
    )


@router.callback_query(F.data == CB_BUY)
async def start_payment(callback: CallbackQuery) -> None:
    """Счёт на подписку. Звёзды не требуют платёжного провайдера."""
    try:
        link = await callback.bot.create_invoice_link(
            title="Доступ к приложению",
            description=(
                "Дневник питания, распознавание еды по фото и голосу, тренировки, "
                "замеры и прогресс. Списывается раз в месяц, отменить можно в любой момент."
            ),
            payload=f"{PAYLOAD_PREFIX}:{callback.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label="Месяц доступа", amount=config.SUB_PRICE_STARS)],
            subscription_period=MONTH_SECONDS,
        )
    except Exception:
        logger.exception("Не удалось создать счёт")
        await callback.answer("Не получилось открыть оплату, попробуй ещё раз", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text=f"⭐ Оплатить {config.SUB_PRICE_STARS}", url=link)
    await callback.message.answer(
        "Счёт готов. После оплаты доступ откроется сразу.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.pre_checkout_query()
async def approve_payment(query: PreCheckoutQuery) -> None:
    """Telegram спрашивает подтверждение перед списанием."""
    await query.answer(ok=True)


@router.message(Command("referral"))
async def my_invite_link(message: Message) -> None:
    """Личная ссылка-приглашение и что по ней уже произошло.

    Ссылка была и раньше, но лежала внутри приложения, на экране «Друзья».
    Человек, который бота в чате и открывает, про неё не знал вовсе — а
    позвать подругу хотят чаще из переписки, чем из приложения.

    Текст меняется вместе с оплатой. Пока доступ бесплатен для всех, про
    подаренные дни здесь нет ни слова: обещать подарок, которым нельзя
    воспользоваться, хуже, чем не обещать ничего.
    """
    async with get_session() as session:
        code = await friends.invite_code(session, message.from_user.id)
        итог = await referrals.summary(session, message.from_user.id)

    link = friends.invite_link(code)
    if not link:
        await message.answer(
            "Ссылка появится, когда бот узнает своё имя в Telegram. "
            "Это чинится на стороне бота, не у тебя — напиши /problem."
        )
        return

    строки = ["Твоя ссылка — по ней подруга попадёт сразу к тебе в друзья:",
              "", link, ""]

    if config.PAYWALL:
        дней_за_анкету = referrals.SIGNUP_DAYS_INVITER
        дней_за_оплату = referrals.PAYMENT_DAYS_INVITER
        строки += [
            f"Дошла до конца анкеты — {дней_за_анкету} "
            f"{plural(дней_за_анкету, 'день', 'дня', 'дней')} доступа тебе и "
            f"столько же ей. Так до {referrals.SIGNUP_LIMIT} подруг.",
            f"Оформила подписку — ещё {дней_за_оплату} "
            f"{plural(дней_за_оплату, 'день', 'дня', 'дней')} тебе. "
            "Тут ограничения нет.",
            "",
        ]
        if итог.invited:
            строки.append(
                f"Пришло по ссылке: {итог.invited} · завели профиль: "
                f"{итог.signed_up} · оформили подписку: {итог.paid}"
            )
            строки.append(
                f"Начислено: {итог.days_earned} "
                f"{plural(итог.days_earned, 'день', 'дня', 'дней')}. "
                f"Наград за анкету осталось: {итог.signups_left}."
            )
    else:
        строки.append("Вы окажетесь в общем недельном рейтинге и увидите "
                      "кристаллы и серии друг друга.")
        if итог.invited:
            строки.append("")
            строки.append(f"Пришло по ссылке: {итог.invited} · завели "
                          f"профиль: {итог.signed_up}")

    await message.answer("\n".join(строки), disable_web_page_preview=True)


async def _thank_inviter_for_payment(message: Message, inviter_id: int,
                                     days: int) -> None:
    """Сказать приглашающей про дни за оплату — не называя, кто заплатил.

    Кто по чьей ссылке пришёл, обе стороны и так знают: они друзья в
    приложении. А вот «твоя подруга заплатила» — это уже про чужие деньги,
    и человек не просил об этом рассказывать. Поэтому фраза безымянная.
    """
    if not days or not inviter_id:
        return

    слово = plural(days, "день", "дня", "дней")
    try:
        await message.bot.send_message(
            inviter_id,
            f"Человек, которого ты привела, оформил подписку — тебе "
            f"{days} {слово} доступа в подарок. Спасибо!"
        )
    except Exception as error:  # noqa: BLE001 — чужой чат нам не подчиняется
        logger.warning("Не смогли поблагодарить %s за оплату: %s", inviter_id, error)


@router.message(F.successful_payment)
async def payment_received(message: Message) -> None:
    """Оплата прошла — открываем доступ. Сюда же приходят автопродления."""
    payment = message.successful_payment

    async with get_session() as session:
        await activate(
            session,
            message.from_user.id,
            days=config.SUB_PERIOD_DAYS,
            source=SubscriptionSource.STARS,
            amount=payment.total_amount,
            charge_id=payment.telegram_payment_charge_id or "",
            is_recurring=bool(payment.is_recurring),
        )
        # Если этого человека кто-то привёл — приглашающей идут дни. Платят
        # один раз за приведённого, сколько бы он потом ни продлевал:
        # награда за человека, а не процент с каждого платежа.
        пригласила, дней = await referrals.reward_payment(session, message.from_user.id)

    await _thank_inviter_for_payment(message, пригласила, дней)

    if payment.is_recurring and not payment.is_first_recurring:
        await message.answer("⭐ Подписка продлена на месяц. Спасибо!")
        return

    await message.answer(
        "Готово, доступ открыт! 🎉\n\n"
        "Всё на месте: фото еды, голосовые, тренировки, замеры и прогресс.\n"
        "Отменить подписку можно в любой момент в настройках Telegram."
    )


@router.message(Command("id"))
async def show_my_id(message: Message) -> None:
    """Свой номер в Телеграме — чтобы вписать его в ADMIN_IDS.

    Команда доступна всем: номер и так виден любому, кому человек пишет,
    а владельцу иначе пришлось бы ставить постороннего бота ради одной цифры.
    """
    me = message.from_user.id
    known = me in config.ADMIN_IDS
    lines = [f"Твой номер в Телеграме: `{me}`"]
    if known:
        lines.append("\nТы вписан(а) в ADMIN_IDS — отчёты и предупреждения приходят сюда.")
    else:
        lines.append(
            "\nВ ADMIN_IDS тебя нет. Если это твой бот, впиши номер на сервере:\n"
            "`bash set-admin.sh " + str(me) + "`\n\n"
            "Пока список пуст, платный доступ выключен, а отчёты о расходах "
            "и предупреждения уходить некуда."
        )
    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.message(Command("circles"))
async def preview_circles(message: Message) -> None:
    """Показать владелице оба кружка знакомства — по требованию.

    Зачем отдельная команда. Оба момента одноразовые: «Привет» приходит
    после согласия с условиями, «Готово» — после анкеты, и человек, у
    которого профиль давно заведён, не увидит их уже никогда. Владелице
    же надо знать, что именно получает новый человек, — иначе судить о
    первом знакомстве приходится по чужому пересказу.

    Заводить ради этого сброс анкеты нельзя: он стёр бы настоящий профиль.
    Поэтому кружки просто присылаются ещё раз, и только владельцу — для
    всех остальных команды словно не существует.

    Чего нет на диске — качается прямо здесь, а не «при следующем
    перезапуске». Ждать полчаса, чтобы увидеть своё же приветствие, —
    это не ответ, а отписка; а бот и так умеет качать сам.

    И если не выходит, команда говорит почему. «Кружка нет» без причины —
    тупик: следующий шаг из него не придумать, а в журнал на сервере
    владелица не смотрит, она работает с айпада.
    """
    if message.from_user.id not in config.ADMIN_IDS:
        return

    from services.video_notes import (CIRCLES, circle_path, ensure_circles,
                                      send_circle, состояние)

    когда = {
        "hello": "Это приходит сразу после согласия с условиями, "
                 "перед первым вопросом анкеты.",
        "ready": "А это — когда анкета заполнена, вместе с первым шагом.",
    }

    if any(circle_path(имя) is None for имя in CIRCLES):
        await message.answer("Не все кружки на месте — качаю, секунду…")
        await ensure_circles()

    готовые = [имя for имя in CIRCLES if circle_path(имя) is not None]
    if not готовые:
        строки = ["Кружков на сервере нет, и скачать их сейчас не вышло.", ""]
        строки += [f"• {имя} — {состояние(имя)}" for имя in CIRCLES]
        строки.append("")
        строки.append("Пришли мне эти строки — по ним видно, где затык.")
        await message.answer("\n".join(строки))
        return

    await message.answer(
        "Показываю то же, что видит новый человек. "
        "Тебе это придёт по команде, ему — само, один раз в жизни."
    )
    for имя, пояснение in когда.items():
        await message.answer(пояснение)
        if circle_path(имя) is None or not await send_circle(message, имя):
            await message.answer(f"Кружок не показался. Что с ним: {состояние(имя)}")


@router.message(Command("admin"))
async def admin_stats(message: Message) -> None:
    """Сводка для владельца: сколько людей и звёзд."""
    if message.from_user.id not in config.ADMIN_IDS:
        return   # для остальных команды словно не существует

    async with get_session() as session:
        data = await stats(session)

    await message.answer(
        "📊 Подписки\n\n"
        f"Всего людей: {data['total']}\n"
        f"Платят сейчас: {data['active']}\n"
        f"Бесплатно навсегда: {data['lifetime']}\n"
        f"На пробном: {data['trial']}\n"
        f"С автопродлением: {data['recurring']}\n"
        f"Закончилась: {data['expired']}\n\n"
        f"Платили хоть раз: {data['payers']}\n"
        f"Звёзд за 30 дней: {data['stars_30d']} ⭐\n\n"
        "Сводка сейчас: /report (или /report неделя)\n"
        "Выдать доступ вручную: /grant ID ДНЕЙ\n"
        "Открыть навсегда: /grant ID навсегда"
    )


# Telegram обрезает сообщение длиннее этого — режем сами, по строкам.
STATUS_CHUNK = 3500


@router.message(Command("status"))
async def owner_status(message: Message) -> None:
    """То же, что показывает bash status.sh, только в чат.

    До сих пор техническую сводку — версию, диск, картинки, приглашения —
    можно было увидеть только из консоли сервера. Когда консоль перестала
    открываться, узнать, что с ботом, стало неоткуда: единственный канал
    диагностики оказался тем самым, который и сломался.
    """
    if message.from_user.id not in config.ADMIN_IDS:
        return

    from services import status as status_service

    # Собираем в том же цикле событий, в котором живёт бот. Раньше сводка
    # уезжала в отдельный поток со своим циклом (`asyncio.run`) — ради
    # обращения к git, которое и правда останавливает весь бот. Но вместе с
    # git туда уехали и запросы к базе, а соединения asyncpg принадлежат
    # тому циклу, в котором они открыты: взятое из общего пула соединение в
    # чужом цикле падает с «attached to a different loop». Поймано у Лилии
    # на живом сервере — команда диагностики оказалась единственной, которая
    # не работает. Медленные места теперь уходят в поток поодиночке, внутри
    # `collect`, а база остаётся здесь.
    text = await status_service.collect()
    for part in _split(text, STATUS_CHUNK):
        await message.answer(part)


def _split(text: str, limit: int) -> list[str]:
    """Разбить по строкам, не разрывая строку посередине."""
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit and current:
            parts.append(current.rstrip("\n"))
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current.rstrip("\n"))
    return parts or [text]


@router.message(Command("sources"))
async def marketing_report(message: Message) -> None:
    """Воронка: откуда пришли и дошли ли до пользы. Только владельцу.

    Отдельной панели и стороннего сервиса здесь нет намеренно: отчёт
    собирается теми же средствами, что `/admin` и `/report`, и приходит
    туда же — в чат владельцу.

    Свои номера из рабочих показателей исключены. Без этого первые же цифры
    оказываются про Лилию и тех, кто помогал проверять, — то есть про людей,
    которые пришли не по ссылке и вели себя не как гости.
    """
    if message.from_user.id not in config.ADMIN_IDS:
        return   # для остальных команды словно не существует

    дней = 30
    части = (message.text or "").split()
    if len(части) > 1 and части[1].isdigit():
        дней = max(1, min(int(части[1]), 365))

    async with get_session() as session:
        итог = await analytics.report(session, days=дней,
                                      exclude=set(config.ADMIN_IDS))

    строки = [
        f"📈 Воронка за {дней} дн. ({итог.since:%d.%m} — {итог.until:%d.%m}, "
        f"{analytics.REPORT_TZ})",
        "",
        "👥 Люди",
        f"   Новых: {итог.starts_new}",
        f"   Возвращались уже заведённые: {итог.starts_existing}",
        f"   Дошли до конца анкеты: {итог.profiles}",
        f"   Сделали первое полезное действие: {итог.first_actions}",
        f"   Были активны хоть раз: {итог.active_people}",
        f"   Активных дней всего: {итог.active_days}",
    ]

    if итог.actions:
        строки += ["", "✅ Полезные действия (это события, не люди)"]
        for вид, сколько in sorted(итог.actions.items(), key=lambda п: -п[1]):
            строки.append(f"   {analytics.ACTION_NAMES.get(вид, вид)}: {сколько}")

    строки += ["", "🔗 Первый источник (все за всё время)"]
    if итог.sources:
        for метка, сколько in sorted(итог.sources.items(), key=lambda п: -п[1]):
            строки.append(f"   {метка}: {сколько}")
    else:
        строки.append("   пока никого")

    строки += [
        "",
        f"Учёт ведётся с {analytics.STARTED_ON:%d.%m.%Y}. Того, что было "
        "раньше, здесь нет и быть не может.",
        "За другой срок: /sources 7",
    ]

    await message.answer("\n".join(строки))


@router.message(Command("report"))
async def owner_report(message: Message) -> None:
    """Сводка не дожидаясь утра. Слово «неделя» — недельный отчёт."""
    if message.from_user.id not in config.ADMIN_IDS:
        return

    from services import owner_reports

    weekly = "недел" in (message.text or "").lower()
    async with get_session() as session:
        text = await (owner_reports.weekly if weekly else owner_reports.daily)(session)

    await message.answer(text)


@router.message(Command("grant"))
async def grant_access(message: Message) -> None:
    """Выдать доступ вручную — например, подруге или за отзыв."""
    if message.from_user.id not in config.ADMIN_IDS:
        return

    parts = (message.text or "").split()
    forever = len(parts) == 3 and parts[2].lower() in FOREVER_WORDS
    if len(parts) != 3 or not parts[1].isdigit() or not (forever or parts[2].isdigit()):
        await message.answer(
            "Формат: /grant ID ДНЕЙ\n"
            "Например: /grant 123456789 30\n"
            "Или навсегда: /grant 123456789 навсегда"
        )
        return

    user_id = int(parts[1])

    if forever:
        async with get_session() as session:
            await grant_lifetime(session, [user_id])
        await message.answer(f"Пользователю {user_id} открыт бесплатный доступ навсегда.")
        note = "🎁 Тебе открыли бесплатный доступ навсегда. Заходи в приложение!"
    else:
        days = int(parts[2])
        async with get_session() as session:
            subscription = await activate(
                session, user_id, days=days, source=SubscriptionSource.MANUAL
            )
        await message.answer(
            f"Выдано {days} дней пользователю {user_id}.\n"
            f"Доступ до {subscription.expires_at:%d.%m.%Y}."
        )
        note = f"🎁 Тебе открыли доступ на {days} дней. Заходи в приложение!"

    try:
        await message.bot.send_message(user_id, note)
    except Exception:
        logger.info("Не получилось уведомить пользователя %s о выданном доступе", user_id)
