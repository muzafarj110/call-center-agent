# Email Login (OTP) + Guided Web App

Clients now sign in with an email code, get walked through a step-by-step setup
wizard, and always land on their dashboard afterward.

## The user journey (`site/app.html`)
1. **Sign in** — enter email → receive a 6-digit code → enter it. No password.
2. **Setup wizard** (only the first time) — a guided "train" with one question
   per step: business type → name → services/products → hours + language →
   delivery + manager number → connect WhatsApp → review → **Finish**.
3. **Dashboard** — every future login lands here: live counts and three tabs —
   **Pending**, **In progress**, **History** — with one-tap status changes.

## Works immediately in DEV mode (no email yet)
If `RESEND_API_KEY` is **not** set, the code isn't emailed — instead it's shown
on screen (and logged) so you can test the entire flow right now. Turn on real
emails by adding the Resend key below.

## Turn on real emails with Resend
1. Sign up free at https://resend.com.
2. **API Keys → Create API Key** → copy it.
3. (Optional but recommended) **Domains → Add Domain** and verify your domain so
   emails come from `you@yourdomain.com`. To start fast you can skip this and use
   the shared test sender `onboarding@resend.dev` (note: the test sender can only
   deliver to the email you signed up with — fine for your own testing).
4. On Railway → Variables, add:
   | Variable | Value |
   |----------|-------|
   | `RESEND_API_KEY` | your Resend key |
   | `RESEND_FROM` | e.g. `AIBusinessAutomation <noreply@yourdomain.com>` (or leave unset to use `onboarding@resend.dev`) |

Once `RESEND_API_KEY` is set, the dev code stops appearing and real emails go out.

## New backend endpoints
| Endpoint | Purpose |
|----------|---------|
| `POST /auth/request-otp` `{email}` | generate + email a code (dev mode returns it) |
| `POST /auth/verify-otp` `{email,code}` | returns a session `token` + setup status |
| `GET /auth/me` | current user (Bearer token) |
| `POST /setup` | wizard submit — creates the client + products, marks done |
| `GET /my/orders` | dashboard data grouped pending/current/history |
| `POST /my/order-status` `{order_id,status}` | update one of your orders |

All `/auth/me`, `/setup`, `/my/*` calls send `Authorization: Bearer <token>`.

## New MongoDB collections
- `users` — `{email, client_id, setup_complete}`
- `otps` — short-lived codes (10-min expiry)
- `sessions` — `{email, token}`

## Pages in `site/`
- `index.html` — landing (Get started → `app.html`)
- `app.html` — the guided sign-in → wizard → dashboard (this is what clients use)
- `admin.html` — your owner view of all clients + orders
- `onboard.html` — the older single-form onboarding (kept; optional)

## Security notes
- Tokens are random and stored in the `sessions` collection; sign-in is
  passwordless via email possession.
- Set `ADMIN_SECRET` to protect the owner-wide `/clients`, `/orders`, `/products`.
- For production you may later add token expiry and rate-limiting on
  `/auth/request-otp` to prevent email abuse.
