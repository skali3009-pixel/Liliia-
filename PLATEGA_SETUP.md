# Platega: 490 RUB / 30 days

Prepared locally on 2026-10-17. Not deployed or live-tested yet.
Stars stay disabled. No recurring mandates. PAYWALL remains a separate switch;
enabling checkout must not silently remove existing beta or lifetime access.

## Configuration

Set PLATEGA_MERCHANT_ID and PLATEGA_SECRET in the server environment, never Git.
PLATEGA_ENABLED=1 exposes checkout only when both credentials are present.
Callback remains operational with credentials even if new sales are disabled.
Local `.env.platega.local` is an ignored intake file, NOT loaded automatically.
Do not print it, commit it, or send credentials to the chat.

Provider dashboard callback URL after deployment:
https://72-56-90-120.nip.io/payments/platega/callback

API: https://docs.platega.io/ — POST /v2/transaction/process, GET /transaction/{id}.
Payment page chooses the merchant's enabled methods. metadata.userId is the Telegram ID.
Return links open the bot, never activate access. Provider auth plus a separate GET
check validates amount/currency/order before the database transaction grants access.

## Verification before launch

- Payment terms/privacy updated for Platega, version 17.10.2026; verify owner details before launch.
- Test PostgreSQL migration and concurrent duplicate callbacks; SQLite tests alone do not prove row locks.
- Configure callback URL in merchant dashboard; confirm available methods and fee handling.
- Run a controlled real payment with the owner; verify callback, /subscription and /admin.
- Test cancellation, repeated callbacks and refund, including expired and active subscriptions.
- Confirm API response shape/url host against the real merchant. Fail closed on differences.
- Decide beta-to-paid transition separately; do not enable PAYWALL as a side effect.

## Operations

`/tariffs`: one plan and purchase button. `/subscription`: expiry. `/admin`: RUB total.
Each checkout has its own "Проверить оплату" button, bound to its owner.
After uncertain create response, no automatic second POST: inspect provider dashboard
and reconcile the transaction using its payload/order ID. This prevents double billing.
Pending order links are reused; check canceled/expired orders before creating another.
Callback retries are limited by Platega, so a user can also reconcile with the check button.
Full chargeback removes the purchased days once; partial refunds require manual review.

## Platform constraint

Telegram requires Stars for digital purchases inside bots/Mini Apps:
https://core.telegram.org/bots/payments-stars#faq
User explicitly chose Platega-only after disclosure. Provider approval of the bot URL
does not establish Telegram compliance or remove mobile availability risk.
