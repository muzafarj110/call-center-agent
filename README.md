# AIBusinessAutomation — Dynamic Multi-Business WhatsApp AI Platform

One Flask app serves many businesses (baqala, supermarket, pharmacy, restaurant,
hospital/clinic, retail). Each WhatsApp number maps to one client; the agent
adapts its prompt, flow, and data collection to that client's `business_type`.

## Files

| File | Responsibility |
|------|----------------|
| `business_config.py` | The 8 onboarding fields → `ClientConfig`; generates the system prompt + flow + extraction schema per business type. |
| `clients.py` | Registry mapping `phone_number_id` → client config (reads `clients.json`, hot-reloads, per-client WhatsApp token). |
| `sheets.py` | Google Sheets: cached product/menu reads (5 min), customer address memory, save order/booking/lead. |
| `ai.py` | Claude main reply call + second structured-extraction call. Owns the hidden `[[READY]]` confirmation token. |
| `conversation.py` | Per-customer session state + Python-owned YES/NO, escalation, and address detection (EN + AR). |
| `app.py` | Flask webhook (verify + receive), WhatsApp send, CORS, rate limiting, wiring. |

## How a message flows

1. Inbound webhook → identify client by `phone_number_id`.
2. Complaint / "manager" / "human" → escalate to the client's number.
3. If a confirmation is pending and the customer says **yes** → 2nd Claude call
   extracts fields → save to Sheet → reply with the Order/Booking ID.
   (The AI never finalizes; **Python owns YES/NO**.)
4. Otherwise → fetch live products/slots (cached) → build prompt → Claude reply.
   When the AI shows the final summary it appends `[[READY]]`; Python strips it
   and marks the session pending.

## Onboarding a new client

Add an entry to `clients.json` (see `clients.example.json`) keyed by the Meta
`phone_number_id`, then `POST /reload-clients`. No redeploy needed.

The client's Google Sheet needs tabs: `Products`, `Orders`, `Customers`, and
(for hospital/clinic) `Slots`. Share each Sheet with the service-account email
as Editor.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in keys
cp clients.example.json clients.json
python app.py               # dev
# prod: gunicorn -w 2 -b 0.0.0.0:$PORT app:app
```

Set the Meta webhook callback to `https://<your-railway-app>/webhook` and the
verify token to `WHATSAPP_VERIFY_TOKEN`.

## ⚠️ Always test language detection after any change

Confirm Arabic input gets Arabic replies and English gets English, with no
mid-conversation switching. Clients set to `arabic`/`english` are forced to that
language; `both` mirrors the customer.

## Note on scaling

Session state and rate limiting are in-memory (fine for one Railway instance).
For multiple workers, back `conversation._sessions` and the rate limiter with
Redis — the function interfaces stay the same.
