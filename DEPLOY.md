# Deploying AIShop to Railway

I can't run the deploy for you (no access to your GitHub or Railway from here),
but everything is configured. Run one of the two paths below from your Mac.

## Prerequisites (one time)
- A Railway account + project.
- The service-account JSON for Google Sheets, and the service-account email
  shared as **Editor** on every client Sheet.
- Your Meta WhatsApp **permanent access token**, **verify token**, and each
  number's **phone_number_id**.

## Files that drive the deploy
- `Procfile` / `railway.json` — start command (gunicorn, 1 worker + threads).
- `requirements.txt` — Python deps (Nixpacks installs these).
- `runtime.txt` — pins Python 3.11.9.
- `.gitignore` — keeps `.env`, `clients.json`, and credentials out of git.

---

## Path A — GitHub integration (recommended)

```bash
cd "/Users/muzafarjatoi/Claude/Projects/all-center-agent"
git init                 # skip if already a repo
git add .
git commit -m "Dynamic multi-business WhatsApp platform + Flask integration"
git branch -M main
git remote add origin https://github.com/YOURNAME/YOURREPO.git   # skip if set
git push -u origin main
```

Then in the Railway dashboard: **New Project → Deploy from GitHub repo →** pick
this repo. Railway auto-builds on every push.

## Path B — Railway CLI

```bash
npm i -g @railway/cli      # if not installed
railway login
cd "/Users/muzafarjatoi/Claude/Projects/all-center-agent"
railway link               # pick/create the project
railway up                 # builds & deploys this directory
```

---

## Set environment variables on Railway

Railway → your service → **Variables**. Set:

| Variable | Value |
|----------|-------|
| `ANTHROPIC_API_KEY` | your Claude API key |
| `CLAUDE_MODEL` | `claude-opus-4-5` |
| `WHATSAPP_TOKEN` | Meta permanent token (fallback if not per-client) |
| `WHATSAPP_VERIFY_TOKEN` | any string; reuse it in the Meta webhook setup |
| `GOOGLE_CREDENTIALS_JSON` | the **entire** service-account JSON, one line |
| `CLIENTS_JSON` | the clients registry JSON (see `clients.example.json`) |
| `ADMIN_SECRET` | a secret to protect `/reload-clients` |

`CLIENTS_JSON` keeps client WhatsApp tokens out of git. (Locally you can use a
`clients.json` file instead — the app prefers the file when present.)

## Point Meta at the deployment
1. Copy your Railway public URL, e.g. `https://aishop.up.railway.app`.
2. Meta App → WhatsApp → Configuration → **Webhook**:
   - Callback URL: `https://<your-app>.up.railway.app/webhook`
   - Verify token: the value of `WHATSAPP_VERIFY_TOKEN`
   - Subscribe to the **messages** field.
3. Confirm `GET /health` returns `{"status":"ok"}` and shows your client count.

## Smoke test after deploy
- `curl https://<your-app>.up.railway.app/health`
- Send a WhatsApp message to a connected number; confirm a reply.
- **Test language detection:** Arabic in → Arabic out, English in → English out.
- Place a test order through to the confirmation ID; check the Orders tab.

## Onboarding more clients later
Update `CLIENTS_JSON` (or `clients.json`) and `POST /reload-clients` with header
`X-Admin-Secret: <ADMIN_SECRET>` — no redeploy needed.
