# Self-Service Client Onboarding

Clients fill a web form → a row is written to a **master "Clients" Google Sheet**
→ the backend reads clients from that sheet (cached 60s) and routes WhatsApp
messages by `phone_number_id`. New clients persist across redeploys, no env edits.

## 1. Create the master Clients sheet (one time)

1. Create a new Google Sheet, e.g. "AIShop — Clients".
2. Share it (Editor) with the service-account email from `credentials.json`.
3. Add a tab named **Clients** with this header row (row 1, columns A–M):

```
business_name | business_type | products | working_hours | delivery_charge | escalation_number | language | sheet_id | currency | phone_number_id | whatsapp_token | status | created_at
```

(The backend auto-writes this header on first onboard if missing.)

4. Copy the sheet's ID from its URL.

## 2. Set env vars on Railway

| Variable | Value |
|----------|-------|
| `MASTER_SHEET_ID` | the master Clients sheet ID |
| `ONBOARD_KEY` | optional shared key clients must enter on the form (anti-spam) |

When `MASTER_SHEET_ID` is set, the master sheet becomes the source of truth and
`CLIENTS_JSON` / `clients.json` are ignored. **Migrate your existing Daily Fresh
client into the master sheet** as the first row (with its `phone_number_id` and
`status = active`) so it keeps working.

## 3. Host the form

`onboard.html` is a standalone page. Deploy it to Netlify (drag-drop the file, or
add to your dashboard repo). Before deploying, confirm the `API_BASE` constant at
the bottom of the file points to your backend:

```js
const API_BASE = "https://production-call-center.up.railway.app";
```

## 4. How a client onboards

1. Client opens the form, fills business name, type, services, hours, language,
   escalation number, and **their own Google Sheet ID** (with Products/Orders/
   Customers tabs; clinics also need a Slots tab). Enter the onboard key if set.
2. They submit → saved to the master sheet as **pending** (no WhatsApp number yet).
3. You connect their WhatsApp number in Meta, then put its `phone_number_id`
   (and `whatsapp_token` if it's a different Meta account) into their row and set
   `status = active`. Within ~60s the bot is live for that number — or call
   `POST /reload-clients` to apply instantly.

## API endpoints

- `POST /onboard` — body = the form fields; header `X-Onboard-Key` if `ONBOARD_KEY` set.
- `GET /clients` — list active clients (protect with `ADMIN_SECRET` header `X-Admin-Secret`).
- `POST /reload-clients` — force re-read of the master sheet.

## Per-client sheet requirements

Each client's own Google Sheet (the `sheet_id` they enter) needs tabs:
- **Products** — items/menu/specialties (shared with the service account, Editor).
- **Orders** — bookings/orders are appended here.
- **Customers** — remembered names/addresses.
- **Slots** — (clinics/hospitals only) available appointment times.

Every client sheet must also be shared with the service-account email.

## Status values

`active` = routed live · `pending` = saved, awaiting WhatsApp number ·
`paused`/`disabled` = ignored by the router.
