"""Отчёты владельцу: утренняя сводка и итоги недели.

Правило одно: сообщение читается за минуту и заканчивается понятным
выводом, а не набором чисел. Если считать вывод не из чего — так и
написано, чего не хватает. Никаких имён и содержимого переписки: владельцу
нужны цифры, а не чужие дневники.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

import config
from services import metrics
from services import notifications
from services.subscriptions import stats
from services.usage import spent_today
from utils.disk import usage as disk_usage


def _money_lines(money: metrics.Money) -> list[str]:
    """Экономика: сходится ли подписка с расходами."""
    lines = [f"💵 Деньги за {money.days} дн."]

    if money.stars:
        lines.append(
            f"   Пришло: {money.stars} ⭐ ≈ {money.revenue_usd:.2f} $ "
            f"({money.payers} платящих)"
        )
    else:
        lines.append("   Выручки нет: оплата ещё не включена")

    lines.append(f"   Расход на модель: {money.model_usd:.2f} $")
    if money.fixed_usd:
        lines.append(f"   Постоянные расходы: {money.fixed_usd:.2f} $")
    if money.tax_usd:
        lines.append(f"   Налог: {money.tax_usd:.2f} $")

    if money.active:
        lines.append(
            f"   Один живой человек обошёлся в {money.per_active_usd:.2f} $ "
            f"за {money.days} дн."
        )

    if not money.known:
        # Без постоянных расходов «прибыль» была бы враньём: сервер и
        # бухгалтерия платятся всё равно.
        lines.append(
            "   Прибыль не считаю: не заполнены постоянные расходы "
            "(сервер, бухгалтерия) — FIXED_COSTS_USD в .env"
        )
        return lines

    lines.append(f"   Итого: {money.profit_usd:+.2f} $")
    return lines


def _breakeven_line(money: metrics.Money) -> str | None:
    """Сколько платящих нужно, чтобы выйти в ноль."""
    need = money.breakeven_payers
    if need is None:
        return None
    income = money.per_payer_usd
    tail = "" if money.payers >= need else f", сейчас {money.payers}"
    return (f"   Чтобы окупалось, нужно {need} платящих по {income:.2f} $ "
            f"с подписки{tail}")


async def daily(session: AsyncSession) -> str:
    """Утренняя сводка: что было за сутки."""
    people = await metrics.audience(session, days=1)
    doing = await metrics.activity(session, days=1)
    spend = await spent_today(session, metrics.now().date())
    month = await metrics.money(session, days=30)
    subs = await stats(session)
    disk = disk_usage()

    lines = [
        "☀️ Сводка за сутки",
        "",
        "👥 Люди",
        f"   Всего зарегистрировано: {people.registered} "
        f"(дошли до конца анкеты: {people.onboarded})",
        f"   Пришло за сутки: {people.joined}",
        f"   Пользовались: {people.active} за сутки, {people.active_7d} за неделю",
    ]

    if config.PAYWALL:
        lines.append(
            f"   Платят: {subs['active']} · на пробном: {subs['trial']} · "
            f"бесплатно навсегда: {subs['lifetime']}"
        )
    else:
        lines.append("   Оплата выключена — бот бесплатный для всех")

    lines += [
        "",
        "📝 Записей за сутки",
        f"   Еда: {doing.meals} · фото: {doing.photos} · голос: {doing.voices}",
        f"   Подбор блюд: {doing.dishes} · тренировки: {doing.workouts} · "
        f"замеры: {doing.measurements}",
        "",
        "💰 Расход на модель",
        f"   Сегодня: {spend.total_usd:.2f} $ ({spend.calls} запросов)",
        f"   Остаток до потолка: {spend.left_usd:.2f} $ из "
        f"{config.DAILY_COST_LIMIT_USD:.0f} $",
    ]

    if spend.by_kind:
        names = {"photo": "фото", "text": "текст", "voice": "голос",
                 "build": "подбор блюд"}
        parts = ", ".join(
            f"{names.get(kind, kind)} {value:.2f} $"
            for kind, value in sorted(spend.by_kind.items(), key=lambda item: -item[1])
        )
        lines.append(f"   На что: {parts}")

    # Главный вопрос владельца — сходится ли одно с другим — должен быть
    # виден каждый день, а не только по пятницам.
    lines += ["", *_month_line(month)]
    lines += ["", f"💾 Диск: занято {disk.percent}%, свободно {disk.free_gb} ГБ"]
    return "\n".join(lines)


def _month_line(money: metrics.Money) -> list[str]:
    """Экономика одной-двумя строками — для утренней сводки."""
    lines = [
        f"📊 За 30 дней: выручка {money.revenue_usd:.2f} $, "
        f"расходы {money.costs_usd:.2f} $"
    ]
    if money.known:
        lines.append(f"   Итого: {money.profit_usd:+.2f} $")
    breakeven = _breakeven_line(money)
    if breakeven:
        lines.append(breakeven)
    return lines


KIND_RU = {
    "turn": "Твой ход",
    "meal": "Еда",
    "water": "Вода",
    "movement": "Движение",
    "world": "Мир и события",
    "evening": "Итоги дня",
    "achievement": "Достижения",
}


def _notification_lines(rows) -> list[str]:
    """Какие сообщения бота работают, а какие только тратят внимание.

    Главная мера — доля нажатий, а не число отправленных. Сообщение,
    которое открывают и после которого ничего не делают, успешным не
    считается. Сначала показываем худшее: чинить надо его.
    """
    if not rows:
        return ["", "🔔 Сообщения бота", "   Пока не о чем говорить: ничего не отправлялось"]

    lines = ["", "🔔 Сообщения бота (за месяц)"]
    for row in rows:
        name = KIND_RU.get(row.name, row.name)
        line = (f"   {name}: {row.sent} шт. · нажали {round(row.action_rate * 100)}%"
                f" · заглянули {round(row.open_rate * 100)}%")
        if row.snoozed or row.disabled:
            line += f" · просили тише {round(row.harm_rate * 100)}%"
        lines.append(line)

    lines += _verdicts(rows)
    return lines


# Меньше этого числа отправленных выводы не делаем: три сообщения ничего
# не доказывают.
ENOUGH = 10


def _verdicts(rows) -> list[str]:
    """Что с этим делать. Два разных случая, и путать их нельзя.

    Сообщение, которое не открывают и не нажимают, — мёртвое: его надо
    переписать или выключить. А вот сообщение, после которого приложение
    открывают, но кнопку не жмут, мёртвым не считается: у части из них
    кнопки действия нет вовсе — например, у вечернего «на сегодня
    достаточно», где предлагать больше нечего и не надо.
    """
    out = []
    for row in rows:
        if row.sent < ENOUGH:
            continue
        name = KIND_RU.get(row.name, row.name)
        if row.open_rate < 0.05:
            out.append(f"   ⚠️ «{name}» не работает совсем — переписать или выключить")
        elif row.action_rate < 0.05:
            out.append(f"   💡 «{name}»: заходят, но ничего не делают. "
                       "Может, там нечего нажимать")
    return out[:2]


async def weekly(session: AsyncSession) -> str:
    """Итоги недели: за чем следить и что решать."""
    people = await metrics.audience(session, days=7)
    doing = await metrics.activity(session, days=7)
    week_money = await metrics.money(session, days=7)
    month_money = await metrics.money(session, days=30)
    subs = await stats(session)

    lines = [
        "📅 Неделя целиком",
        "",
        "👥 Люди",
        f"   Всего зарегистрировано: {people.registered}",
        f"   Дошли до конца анкеты: {people.onboarded} "
        f"(бросили на анкете: {people.stuck})",
        f"   Пришло за неделю: {people.joined}",
        f"   Пользовались: {people.active} за неделю, {people.active_30d} за месяц",
    ]

    if people.registered:
        share = round(people.active_30d / people.registered * 100)
        lines.append(f"   Живых от всех пришедших: {share}%")

    if config.PAYWALL:
        lines.append(
            f"   Платят: {subs['active']} · на пробном: {subs['trial']} · "
            f"бесплатно навсегда: {subs['lifetime']} · закончилось: {subs['expired']}"
        )
    else:
        lines.append("   Оплата выключена — бот бесплатный для всех")

    lines += [
        "",
        "🔧 Чем пользуются за неделю",
        f"   Записей еды: {doing.meals}",
        f"   Фото: {doing.photos} · голос: {doing.voices} · подбор блюд: {doing.dishes}",
        f"   Тренировки: {doing.workouts} · замеры: {doing.measurements}",
        "",
        *_money_lines(week_money),
        "",
        "📊 За месяц",
        f"   Выручка: {month_money.revenue_usd:.2f} $ · "
        f"расходы: {month_money.costs_usd:.2f} $",
    ]

    lines += _notification_lines(await notifications.stats(session, days=30))

    breakeven = _breakeven_line(month_money)
    if breakeven:
        lines.append(breakeven)
    if month_money.known:
        lines.append(f"   Итого за месяц: {month_money.profit_usd:+.2f} $")

    return "\n".join(lines)


__all__ = ["KIND_RU", "daily", "weekly"]
