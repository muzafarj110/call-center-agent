# Zernio WhatsApp — New-Client Transport

The platform now supports **two WhatsApp transports side by side**:

- **Meta Cloud API** — existing clients (e.g. Daily Fresh). Unchanged. Routed by
  `phone_number_id` via `POST /webhook`.
- **Zernio** — new clients. They connect their own WhatsApp from the dashboard
  via Zernio's embedded signup (no Meta developer app). Routed by Zernio
  `accountId` via `POST /zernio/webhook`.

Each client document has a `transport` field (`"meta"` or `"zernio"`). The bot's
reply logic is identical for both — only the send/receive plumbing differs.

## What you set up (one time)

1. **Create a Zernio account** at https://zernio.com → get your **API key**.
2. Find your **Profile ID** (Zernio dashboard / `GET /v1/profiles`).
3. **Railway → Variables**, add:

   | Variable | Value |
   |----------|-------|
   | `ZERNIO_API_KEY` | your Zernio API key |
   | `ZERNIO_PROFILE_ID` | your Zernio profile id |
   | `ZERNIO_WEBHOOK_SECRET` | a secret you set when creating the Zernio webhook (recommended) |
   | `PUBLIC_BASE_URL` | this backend's URL, e.g. `https://production-call-center.up.railway.app` |
   | `APP_BASE_URL` | your Netlify site, e.g. `https://yoursite.netlify.app` |
   | `ZERNIO_BASE` | `https://zernio.com/api` (default; only set to override) |

4. **Create a Zernio webhook** (Zernio dashboard → Webhooks, or
   `POST /v1/webhooks`) pointing at:
   `https://production-call-center.up.railway.app/zernio/webhook`
   Subscribe to **`message.received`** (the only event the bot needs). Set the
   same secret as `ZERNIO_WEBHOOK_SECRET`.

## How a new client connects (self-service)

1. Client signs in to the app, completes the setup wizard → saved as **pending**.
2. On their dashboard they see **🔗 Connect WhatsApp**.
3. Clicking it calls `GET /connect/whatsapp/start` → redirects them to Zernio's
   embedded signup (Meta) → they create/select a WhatsApp Business Account and
   number.
4. Zernio redirects back to `GET /connect/whatsapp/callback`, which stores their
   `zernio_account_id`, sets `transport: "zernio"` and `status: "active"`.
5. They're live — inbound messages now hit `/zernio/webhook` and route to them.

## Endpoints added

| Endpoint | Purpose |
|----------|---------|
| `POST /zernio/webhook` | inbound messages from Zernio (HMAC-verified) |
| `GET /connect/whatsapp/start` | begin embedded signup (auth) → `{authUrl}` |
| `GET /connect/whatsapp/callback` | finish connect, attach accountId to client |

## ⚠️ Verify on first real message

The Zernio send endpoint and inbound field names are implemented from the public
docs and parsed defensively, but should be confirmed against your live account:

- **Send:** `zernio_send()` posts to `POST {ZERNIO_BASE}/v1/messages` with
  `{profileId, accountId, platform:"whatsapp", to, text}`. If Zernio's send shape
  differs, adjust that one function.
- **Receive:** `_zernio_extract()` reads `account.accountId`, the contact handle,
  and `message.text`. Check Railway logs on the first inbound message; if a field
  is empty, tweak the field names there.

Cost: Zernio charges ~$2–25/month per number + Meta's pass-through messaging fees.

## Notes
- Meta/Daily Fresh is completely unaffected — it keeps using `/webhook`.
- A client is "connected" once it has either a `phone_number_id` (meta) or a
  `zernio_account_id` (zernio); until then it's pending and not routed.
