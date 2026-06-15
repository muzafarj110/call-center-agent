# Billing (Stripe), Inbox Messaging & Contact

This adds three things to the platform:

1. **Subscription billing** — businesses subscribe (Pro / Business) via Stripe Checkout.
2. **Dashboard inbox** — the business reads WhatsApp conversations and sends manual replies.
3. **Contact form** — a public "Contact us" page that saves inquiries (and optionally emails you).

## New pages (in `site/`)
- `pricing.html` — plans + Stripe checkout (linked from nav).
- `contact.html` — contact form.
- `app.html` — now has a **💬 Messages** tab and an **⭐ Upgrade** link.

## New backend endpoints
| Endpoint | Purpose |
|----------|---------|
| `POST /billing/checkout` | create a Stripe Checkout session for a plan (auth) |
| `POST /billing/webhook` | Stripe webhook → marks the user's plan active |
| `GET  /billing/status` | current plan for the signed-in user |
| `GET  /my/conversations` | list the client's WhatsApp conversations |
| `GET  /my/conversation?customer=` | full thread with one customer |
| `POST /my/send` | send a manual WhatsApp reply (auth) |
| `POST /contact` | public contact-form submission |

New MongoDB collections: `messages` (inbox log), `contacts` (form submissions).
Every inbound and outbound WhatsApp message is logged automatically, so the inbox fills itself.

---

## Stripe setup (to turn on real billing)

1. Create a **Stripe account** at https://stripe.com → switch to **Test mode** first.
2. **Products → Add product** twice:
   - "Pro" — recurring, $29/month → copy its **Price ID** (`price_...`).
   - "Business" — recurring, $99/month → copy its **Price ID**.
3. **Developers → API keys** → copy your **Secret key** (`sk_test_...`).
4. **Developers → Webhooks → Add endpoint**:
   - URL: `https://production-call-center.up.railway.app/billing/webhook`
   - Events: `checkout.session.completed`, `customer.subscription.deleted`
   - Copy the **Signing secret** (`whsec_...`).
5. **Railway → Variables**, add:

   | Variable | Value |
   |----------|-------|
   | `STRIPE_SECRET_KEY` | `sk_test_...` |
   | `STRIPE_WEBHOOK_SECRET` | `whsec_...` |
   | `STRIPE_PRICE_PRO` | the Pro price id |
   | `STRIPE_PRICE_BUSINESS` | the Business price id |
   | `APP_BASE_URL` | `https://ai-automation-call-center.netlify.app` (already set) |

6. Deploy (push), then on the pricing page choose **Pro** → you'll be sent to Stripe Checkout.
   Use Stripe's test card `4242 4242 4242 4242`, any future date, any CVC.
7. After paying, Stripe calls the webhook → your plan shows as **Pro** in the app.

Go to **Live mode** and repeat steps 2–5 with live keys when you're ready to charge real money.

## Contact form notifications (optional)
Set `CONTACT_TO` (your email) on Railway — with `RESEND_API_KEY` already set, each
contact submission emails you. Without it, submissions are still saved to the
`contacts` collection.

## Deploy
- **Backend:** `git add -A && git commit -m "Billing, inbox, contact" && git push`
- **Website:** re-drag the `site/` folder onto Netlify.

## Notes
- The **Messages** inbox only fills once a client's WhatsApp is connected and
  customers start chatting (messages are logged from that point on).
- Manual replies obey WhatsApp's 24-hour window (free-form only within 24h of the
  customer's last message) — same as the AI replies.
