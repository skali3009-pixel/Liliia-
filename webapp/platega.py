"""Provider callbacks: independent of Telegram initData and checkout visibility."""
import hmac
from aiohttp import web
import config
from services import platega


async def callback(request):
    if not platega.configured():
        raise web.HTTPServiceUnavailable()
    if not (hmac.compare_digest(request.headers.get("X-MerchantId", "").encode(), config.PLATEGA_MERCHANT_ID.encode())
            and hmac.compare_digest(request.headers.get("X-Secret", "").encode(), config.PLATEGA_SECRET.encode())):
        raise web.HTTPUnauthorized()
    try:
        body = await request.json()
        transaction_id = body["id"]
    except (ValueError, TypeError, KeyError):
        raise web.HTTPBadRequest()
    try:
        await platega.reconcile(transaction_id)
    except platega.PaymentError:
        # Non-200 requests a provider retry, including temporary API failure.
        raise web.HTTPServiceUnavailable(text="Payment verification pending")
    return web.Response(status=200)
