# AURA identity migration — 22 October 2026

User authorized migration to @aura_scalia_bot and the exact operational notice
to existing users AFTER verification. Source: @Scalia_fit_food_bot.
Monthly price 490 RUB, 30 days, no trial remain unchanged.

One existing database and media directory are retained. User identity is Telegram
user_id; subscriptions, diary and measurements are not copied or rewritten.
FSM includes bot ID: unfinished old-chat dialogs are not replayed in the new bot.
The old identity runs a redirect-only polling dispatcher in the same process.
No scheduler or payment handlers run under the old identity.

New-bot product notifications and payment notices wait for private contact.
Migration announcements are an explicit operator action, never a startup job.
Delivery is claimed durably before send. Sent, blocked and ambiguous outcomes
are not automatically retried; a crash after claim may omit a notice rather
than send a duplicate. Existing unpaid Platega URLs may still return to the old
bot; it redirects to the new bot and server payment reconciliation is retained.

Commands through existing operator wrapper:
- `sudo aura-run status --bot-migration inspect`
- `sudo aura-run status --bot-migration configure` (new token on stdin only)
- `sudo aura-service restart`
- Verify identities/menu, same data counts/subscription digest, test account,
  Mini App signature/API, service logs, old redirect identity.
- `sudo aura-run status --bot-migration broadcast` only after verification.

Before configuration take `sudo aura-run backup --local`. Configure stores the
original .env mode 0600 under ignored data/bot-migration-20261022 and refuses
unexpected identity, existing webhook, old Telegram progress-photo references,
or repeated configuration. It prints no tokens.

Rollback: `sudo aura-run status --bot-migration rollback`, then
`sudo aura-service restart`. Keep the same database. Do not restore an old
database over new user actions/payments. The old bot description is restored;
startup reapplies its menu and commands. Do not revoke the source token while
the redirect and migration notice are still needed.

Telegram rules checked: https://core.telegram.org/bots/api#sending-files
and https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
New token changes Mini App signature key; Telegram file_id is bot-specific.
The compatibility check rejects stored old progress-photo references; food
photos are not retained in meal records. Trainer MP4/static media use HTTPS.
