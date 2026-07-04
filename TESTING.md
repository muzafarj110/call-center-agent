# AIBusinessAutomation — Feature Test Guide

Two layers: **A) automated tests** (fast, run anytime) and **B) manual
click-through** of the live site + WhatsApp. Do A after every code change; do B
before a demo.

---

## A. Automated tests (60 checks, no deploy needed)

In Terminal:

```
cd /Users/muzafarjatoi/Claude/Projects/all-center-agent
python3 tests/test_harness.py
```

Expect the last line: `60/60 passed`. If any line says `[FAIL] …`, it prints
what broke — send it to me. This covers: onboarding, OTP auth, language
detection (AR/EN/multi), order + restaurant + booking flows, the YES/NO
handshake, escalation, address memory, admin auth guards, billing webhook,
contact, enquiry (call/WhatsApp), sandbox bind/rebind, and the duplicate-client
fix.

---

## B. Manual test — live site + WhatsApp

Site: https://ai-automation-call-center.netlify.app
Before testing UI changes, re-upload `site/` to Netlify and open pages with
`?fresh=1` (or Cmd+Shift+R) so you're not on a cached version.

Every error message now shows **(HTTP status) + reason + endpoint**, so if a step
fails, the on-screen text tells you where.

### 1. Sign up (OTP)
- Open `/app.html` → enter an email (use `you+test1@gmail.com`) → Send code.
- ✅ Pass: OTP screen shows; with `ALLOW_DEV_OTP=1` the code shows on screen,
  otherwise it arrives by email.
- ❌ If blocked: the message shows why (e.g. HTTP 503 = email not configured).

### 2. Verify + wizard
- Enter the code → Verify.
- ✅ Pass: lands on "What kind of business?" wizard.

### 3. Onboard a business
- Pick a type (e.g. **Beach Club**), name it, add services one per line
  (`VIP Cabana - 80`, `Sunbed - 15`), hours, language **Auto — all languages**,
  finish.
- ✅ Pass: dashboard loads with the business name; Review step shows the correct
  item count.

### 4. Dashboard
- ✅ Pass: shows Pending / In progress / History (empty until a booking happens)
  and a "WhatsApp not connected" banner. Empty = normal, not a bug.

### 5. Connect WhatsApp (sandbox)
- Click **Connect WhatsApp → Use the Zernio sandbox**.
- ✅ Pass: confirmation text appears ("Sandbox enabled…"), no error.

### 6. WhatsApp booking — the main demo (multilingual)
- From your activated test phone, message the sandbox number **+1 202 908 7457**.
- Send in a foreign language, e.g. Italian: *"Vorrei prenotare una cabana per
  domani"*.
- ✅ Pass: the agent replies **in Italian**, collects date/people/name, shows a
  summary, and asks to confirm. Reply *"sì"* → you get **Booking confirmed +
  BKG… id**, and the booking appears on the dashboard (Pending).
- Repeat in German ("Ich möchte…") / French ("Je voudrais…") to show it switches
  language per customer.
- ❌ If no reply: check Zernio → Webhooks → **Delivery Logs** for `message.received`
  (200 = reached us). If missing, the message didn't arrive (test phone not
  activated).

### 7. Escalation
- In WhatsApp send *"I want to speak to a manager"* / *"reclamo"*.
- ✅ Pass: customer gets a "a manager will follow up" reply; the manager number
  gets a notification.

### 8. Enquiry page (call / WhatsApp)
- Open `/enquiry.html` → fill name/phone/message → choose **WhatsApp** → send.
- ✅ Pass: "we just replied on WhatsApp" and the number receives an auto-reply.
- Choose **Call**: without Twilio keys it says "saved as pending"; with Twilio
  keys it places an automated call.

### 9. Messages inbox
- In the app, top nav → **Messages**.
- ✅ Pass: WhatsApp conversations list; open one, type a reply, Send → it goes to
  the customer.

### 10. Pricing / billing
- Open `/pricing.html` → choose **Pro**.
- ✅ Pass (with Stripe keys set): redirects to Stripe Checkout (test card
  `4242 4242 4242 4242`). Without keys: a clear "billing not configured" message.

### 11. Contact form
- Open `/contact.html` → submit.
- ✅ Pass: "Thanks! We'll be in touch."

### 12. Admin
- Open `/admin.html` → enter your `ADMIN_SECRET`.
- ✅ Pass: lists clients; pick one → view/update orders.
- ❌ Wrong secret: "Wrong admin secret."

---

## Where to look when something fails
- **On screen:** the new error text (HTTP status + reason + endpoint).
- **Backend:** Railway → your service → Logs (search `[zernio]`, `[ai]`,
  `[billing]`, `[otp]`).
- **WhatsApp delivery:** Zernio → Webhooks → call-center-agent → Delivery Logs.
- Then send me the status code / log line and I'll pinpoint it.
