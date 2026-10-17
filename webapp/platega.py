"""Provider callbacks: independent of Telegram initData and checkout visibility."""
import hmac
import logging
from uuid import UUID, uuid4
from aiohttp import web
import config
from services import platega
from models import PlategaCallback
from webapp.api import BOT_KEY

logger = logging.getLogger(__name__)

# Only these authenticated routes can be used when a subscription has expired.
ACCESS_ROUTES = {("GET", "/api/subscription"), ("POST", "/api/platega/order"),
                 ("POST", "/api/platega/check")}


async def callback(request):
    if not platega.configured():
        raise web.HTTPServiceUnavailable()
    if not (hmac.compare_digest(request.headers.get("X-MerchantId", "").encode(), config.PLATEGA_MERCHANT_ID.encode())
            and hmac.compare_digest(request.headers.get("X-Secret", "").encode(), config.PLATEGA_SECRET.encode())):
        raise web.HTTPUnauthorized()
    try:
        body = await request.json()
        transaction_id = str(UUID(body.get("id") or body.get("Id")))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise web.HTTPBadRequest()
    receipt_id = uuid4().hex
    source = "diagnostic_replay" if request.headers.get("X-Aura-Diagnostic") == "replay" else "callback"
    async with platega.get_session() as session:
        session.add(PlategaCallback(id=receipt_id, transaction_id=transaction_id, received_at=platega.now(), origin=source))
        await session.commit()
    result = "VERIFY_FAILED"
    try:
        result = await platega.reconcile(transaction_id, source=source, bot=request.app.get(BOT_KEY))
    except platega.PaymentError:
        # Non-200 requests a provider retry, including temporary API failure.
        raise web.HTTPServiceUnavailable(text="Payment verification pending")
    finally:
        async with platega.get_session() as session:
            receipt = await session.get(PlategaCallback, receipt_id)
            receipt.result = result
            await session.commit()
        logger.info("Platega %s %s: %s", source, transaction_id, result)
    return web.Response(status=200)


async def subscription(request):
    return web.json_response(await platega.subscription_view(request["user_id"], order_id=request.query.get("order_id")),
                             headers={"Cache-Control": "no-store"})


async def create_order(request):
    try:
        # Amount, duration and owner are always decided on the server.
        order = await platega.create_order(request["user_id"])
    except platega.PaymentError as error:
        return web.json_response({"error": str(error)}, status=409)
    return web.json_response(platega.order_view(order), headers={"Cache-Control": "no-store"})


async def check_order(request):
    try:
        body = await request.json()
        order_id = body["order_id"]
        if not isinstance(order_id, str) or len(order_id) > 32:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise web.HTTPBadRequest()
    try:
        status = await platega.check_order(order_id, request["user_id"], source="web_check", bot=request.app.get(BOT_KEY))
    except platega.PaymentError as error:
        return web.json_response({"error": str(error)}, status=409)
    data = await platega.subscription_view(request["user_id"], order_id=order_id)
    data["checked_status"] = status
    return web.json_response(data, headers={"Cache-Control": "no-store"})
