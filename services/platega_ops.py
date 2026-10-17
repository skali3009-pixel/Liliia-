"""Scoped operator inspection and checkout for a configured test account."""
import asyncio
import json
import sys
from sqlalchemy import select, func
from db import get_session, engine
from models import User, Subscription
from services import platega
from services.legal import LEGAL_VERSION


async def main():
    try:
        action, value = sys.argv[1:3]
        if action == "inspect":
            async with get_session() as session:
                user = (await session.execute(select(User).where(func.lower(User.username) == value.lstrip("@").lower()))).scalar_one_or_none()
                if not user:
                    print(json.dumps({"found": False})); return
                sub = (await session.execute(select(Subscription).where(Subscription.user_id == user.id))).scalar_one_or_none()
                print(json.dumps({"user_id": user.id, "adult": bool(user.age and user.age >= 18),
                    "consent_current": user.legal_version == LEGAL_VERSION and bool(user.legal_accepted_at),
                    "expires_at": sub.expires_at.isoformat() if sub else None,
                    "lifetime": sub.lifetime if sub else False}))
        elif action in {"create", "send-test-ruble", "replace-test-ruble"}:
            user_id = int(value)
            import config
            if user_id not in config.PLATEGA_TEST_USER_IDS:
                raise platega.PaymentError("Account is not enabled for payment testing")
            if action == "replace-test-ruble":
                from models import PlategaOrder
                async with get_session() as session:
                    old = (await session.execute(select(PlategaOrder).where(
                        PlategaOrder.user_id == user_id, PlategaOrder.amount == 1,
                        PlategaOrder.status == "PENDING").with_for_update())).scalars().all()
                    for item in old:
                        data = await platega.api("GET", "/transaction/" + item.transaction_id)
                        if (data.get("status") != "PENDING" or data.get("payload") != item.id
                                or data.get("id") != item.transaction_id or data.get("paidAmount", 0) != 0):
                            raise platega.PaymentError("Old payment needs review before replacement")
                        # Local replacement is NOT provider cancellation. A late payment
                        # still goes through normal verification and fulfillment.
                        item.status = "SUPERSEDED"
                    await session.commit()
            order = await platega.create_order(user_id, one_ruble_test=action != "create")
            if action != "create":
                from aiogram import Bot
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                keyboard = InlineKeyboardBuilder()
                keyboard.button(text="Оплатить тест · 1 ₽", url=order.url)
                keyboard.button(text="Проверить оплату", callback_data=f"platega:check:{order.id}")
                keyboard.adjust(1)
                async with Bot(config.BOT_TOKEN) as bot:
                    message = await bot.send_message(user_id,
                        "Новый тест подключения Platega — 1 ₽ плюс комиссия выбранного способа оплаты. "
                        "Итоговую сумму Platega показывает до подтверждения. Это реальный разовый платёж, без автосписаний. "
                        "После подтверждения начислим 30 дней доступа.\n\n"
                        "Предыдущие ссылки не оплачивай: отменить неоплаченный счёт через API Platega не удалось. "
                        "Обычный тариф остаётся 490 ₽ за 30 дней.",
                        reply_markup=keyboard.as_markup())
                    print(json.dumps({"telegram_message_id": message.message_id, "sent": True}))
            print(json.dumps({"order_id": order.id, "url": order.url, "amount": order.amount, "days": order.days}))
        elif action == "check":
            # Operator status is limited to configured test users.
            import config
            from models import PlategaOrder
            async with get_session() as session:
                order = await session.get(PlategaOrder, value)
                if not order or order.user_id not in config.PLATEGA_TEST_USER_IDS:
                    raise platega.PaymentError("Test order not found")
                user_id = order.user_id
            print(json.dumps({"status": await platega.check_order(value, user_id)}))
        else:
            raise ValueError("Unknown operation")
    except platega.PaymentError as error:
        print(str(error)); sys.exit(2)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
