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
        elif action == "create":
            user_id = int(value)
            import config
            if user_id not in config.PLATEGA_TEST_USER_IDS:
                raise platega.PaymentError("Account is not enabled for payment testing")
            order = await platega.create_order(user_id)
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
