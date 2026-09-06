"""Учёт расходов на модель: сколько потратили и не пора ли притормозить.

Три задачи. Первая — видеть деньги: без учёта счёт за месяц становится
сюрпризом. Вторая — не дать счёту взорваться: дневной потолок останавливает
только распознавание, всё остальное продолжает работать. Третья — не дать
одному человеку съесть бюджет за всех.

Цены — из прейскуранта Anthropic, доллары за миллион токенов. Чтение из
кэша стоит примерно в десять раз дешевле обычного входа, запись в кэш —
в 1,25 раза дороже.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import ApiUsage

logger = logging.getLogger(__name__)

# Доллары за миллион токенов: (вход, выход).
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Если модель незнакомая, считаем по самой дорогой из известных: лучше
# переоценить расход, чем недооценить и проехать мимо потолка.
FALLBACK_PRICE = (5.0, 25.0)

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


@dataclass(frozen=True)
class Spend:
    """Сколько потрачено за день и на что."""

    total_usd: float
    calls: int
    by_kind: dict[str, float]

    @property
    def left_usd(self) -> float:
        return max(config.DAILY_COST_LIMIT_USD - self.total_usd, 0.0)


def price_of(model: str) -> tuple[float, float]:
    return PRICES.get(model, FALLBACK_PRICE)


def cost_usd(model: str, *, input_tokens: int = 0, output_tokens: int = 0,
             cache_write_tokens: int = 0, cache_read_tokens: int = 0) -> float:
    """Стоимость одного запроса в долларах."""
    in_price, out_price = price_of(model)
    million = 1_000_000
    return (
        input_tokens * in_price / million
        + output_tokens * out_price / million
        + cache_write_tokens * in_price * CACHE_WRITE_MULTIPLIER / million
        + cache_read_tokens * in_price * CACHE_READ_MULTIPLIER / million
    )


def _field(usage, *names: str) -> int:
    """Достать число из ответа SDK: имена полей у разных версий отличаются."""
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return 0


async def record(session: AsyncSession, *, user_id: int | None, kind: str,
                 model: str, usage) -> float:
    """Записать расход по ответу модели. Возвращает стоимость в долларах."""
    if usage is None:
        return 0.0

    values = dict(
        input_tokens=_field(usage, "input_tokens"),
        output_tokens=_field(usage, "output_tokens"),
        cache_write_tokens=_field(usage, "cache_creation_input_tokens"),
        cache_read_tokens=_field(usage, "cache_read_input_tokens"),
    )
    price = cost_usd(model, **values)

    session.add(ApiUsage(user_id=user_id, kind=kind, model=model,
                         cost_usd=price, day=date.today(), **values))
    await session.commit()
    return price


async def spent_today(session: AsyncSession, day: date | None = None) -> Spend:
    """Сколько потрачено за сегодня и на что именно."""
    today = day or date.today()
    rows = (await session.execute(
        select(ApiUsage.kind, func.sum(ApiUsage.cost_usd), func.count(ApiUsage.id))
        .where(ApiUsage.day == today).group_by(ApiUsage.kind)
    )).all()

    by_kind = {kind: round(float(total or 0), 4) for kind, total, _ in rows}
    return Spend(total_usd=round(sum(by_kind.values()), 4),
                 calls=sum(count for _, _, count in rows), by_kind=by_kind)


async def over_budget(session: AsyncSession) -> bool:
    """Исчерпан ли дневной потолок расходов."""
    if config.DAILY_COST_LIMIT_USD <= 0:
        return False
    return (await spent_today(session)).total_usd >= config.DAILY_COST_LIMIT_USD


async def calls_today(session: AsyncSession, user_id: int, kind: str) -> int:
    """Сколько раз человек уже пользовался платной функцией сегодня."""
    return (await session.execute(
        select(func.count(ApiUsage.id)).where(
            ApiUsage.user_id == user_id, ApiUsage.kind == kind, ApiUsage.day == date.today()
        )
    )).scalar() or 0


async def photo_limit_left(session: AsyncSession, user_id: int) -> int:
    """Сколько распознаваний фото осталось человеку сегодня."""
    if config.PHOTO_LIMIT_PER_DAY <= 0:
        return 10 ** 6
    return max(config.PHOTO_LIMIT_PER_DAY - await calls_today(session, user_id, "photo"), 0)


async def cleanup(session: AsyncSession, keep_days: int = 90) -> int:
    """Убрать старые записи: для отчётов хватает трёх месяцев."""
    from sqlalchemy import delete

    edge = date.today() - timedelta(days=keep_days)
    result = await session.execute(delete(ApiUsage).where(ApiUsage.day < edge))
    await session.commit()
    return result.rowcount or 0


def render_report(spend: Spend) -> str:
    """Дневной отчёт о расходах для владельца."""
    if not spend.calls:
        return "💰 Вчера на распознавание не потратили ничего."

    names = {"photo": "фото", "text": "текст", "voice": "голос", "build": "подбор блюд"}
    parts = ", ".join(f"{names.get(kind, kind)} {value:.2f} $"
                      for kind, value in sorted(spend.by_kind.items(),
                                                key=lambda item: -item[1]))
    return (f"💰 Расход на модель за сутки: {spend.total_usd:.2f} $ "
            f"({spend.calls} запросов)\n{parts}")


__all__ = ["CACHE_READ_MULTIPLIER", "CACHE_WRITE_MULTIPLIER", "PRICES", "Spend",
           "calls_today", "cleanup", "cost_usd", "over_budget", "photo_limit_left",
           "price_of", "record", "render_report", "spent_today"]
