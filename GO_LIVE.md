# Go Live — Everything Online

Two parts go online: the **backend** (Railway, already have it) and the
**website** (`site/` folder → Netlify). Here's the full checklist.

---

## ✅ What you need to do (only you can do these)

### 1. MongoDB Atlas (~10 min, one-time)
Follow `MONGODB_SETUP.md`: create free M0 cluster → DB user → Network Access
`0.0.0.0/0` → copy the `MONGODB_URI`.

### 2. Set Railway environment variables
Railway → your service → Variables. Set/confirm:

| Variable | Value |
|----------|-------|
| `MONGODB_URI` | from Atlas |
| `MONGODB_DB` | `aishop` (optional) |
| `ANTHROPIC_API_KEY` | your Claude key |
| `WHATSAPP_TOKEN` | Meta token |
| `WHATSAPP_VERIFY_TOKEN` or `VERIFY_TOKEN` | your verify token |
| `WHATSAPP_PHONE_ID` | default WhatsApp number id |
| `ADMIN_SECRET` | **pick a strong string** (protects admin dashboard) |
| `ONBOARD_KEY` | **pick a string** clients must enter to onboard (anti-spam) |

You can remove the old `CLIENTS_JSON`, `GOOGLE_CREDENTIALS_JSON`, `credentials.json` — no longer used.

### 3. Push the backend code
```bash
cd ~/Claude/Projects/all-center-agent
git add -A
git commit -m "MongoDB migration + website"
git push
```
Railway auto-deploys. Check: `curl https://production-call-center.up.railway.app/health`

### 4. Deploy the website to Netlify (~5 min, one-time)
1. Go to https://app.netlify.com → sign up (free).
2. **Add new site → Deploy manually** → drag the **`site/` folder** onto the page.
3. Netlify gives you a URL like `https://your-name.netlify.app`.
   - Landing page: `/` → `index.html`
   - Onboarding form: `/onboard.html`
   - Admin dashboard: `/admin.html`

### 5. Re-onboard Daily Fresh into MongoDB
Open `https://your-name.netlify.app/onboard.html` and submit Daily Fresh:
business type **grocery**, its products, escalation `971565893710`, language Both,
and its **phone_number_id** (so it's active immediately). Enter the onboard key.

### 6. Point Meta webhook at Railway (if not already)
Meta → WhatsApp → Configuration → Callback URL:
`https://production-call-center.up.railway.app/webhook`, verify token =
`VERIFY_TOKEN`, subscribe to **messages**.

---

## 🔧 What I've already done
- Full MongoDB backend (clients/products/orders/customers/slots).
- `/onboard`, `/clients`, `/products`, `/orders`, `/update-order` APIs.
- User-friendly website in `site/`: landing + onboarding form + admin dashboard.
- All API URLs point to `https://production-call-center.up.railway.app`.

> If your Railway URL ever changes, update `API_BASE` at the bottom of
> `site/onboard.html` and `site/admin.html`.

---

## 🧭 How clients use it
1. You send a client `https://your-name.netlify.app/onboard.html` + the onboard key.
2. They fill their business details and product/service list → submit (saved as **pending**).
3. You connect their WhatsApp number in Meta, paste its `phone_number_id` into
   their record → they're **live**.
4. You monitor everything at `/admin.html` with your `ADMIN_SECRET`.

## ⚠️ After go-live
Always **test language detection** (Arabic in → Arabic out, English in →
English out) and run one full order + one appointment booking end-to-end.
