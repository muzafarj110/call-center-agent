# Moving Call Center Agent from Windows → Mac

Your code already lives in the private GitHub repo
`https://github.com/muz110/call-center-agent`, so the move is mostly: **clone on
the Mac, then bring over the secret files git doesn't track** (`.env`,
`credentials.json`). Nothing about the app is Windows-specific — it's plain
Python + Flask, which runs identically on macOS.

---

## Step 1 — Install the tools on the Mac (one time)

```bash
# Xcode command-line tools (gives you git)
xcode-select --install

# Homebrew (if you don't have it) — https://brew.sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3
brew install python
python3 --version
```

## Step 2 — Authenticate to GitHub (private repo)

Easiest is the GitHub CLI:

```bash
brew install gh
gh auth login        # choose GitHub.com → HTTPS → login with browser
```

(Or create a Personal Access Token at github.com → Settings → Developer
settings → Tokens, and use it as the password when git prompts.)

## Step 3 — Clone the repo

```bash
mkdir -p ~/Projects && cd ~/Projects
git clone https://github.com/muz110/call-center-agent.git
cd call-center-agent
```

## Step 4 — Bring over the secret files (NOT in git)

These exist only on your Windows PC at `C:\Users\Muzafar.Jatoi\Call_Center_Agent\`
and must be copied manually:

- `.env` — API keys / tokens
- `credentials.json` — Google service-account JSON
- anything in `clients/` that isn't committed

Move them via AirDrop, a USB drive, or a private cloud folder. Drop them into
`~/Projects/call-center-agent/` next to the code. **Do not** email them or
commit them to git.

> Tip: confirm they're git-ignored on the Mac with `git status` — `.env` and
> `credentials.json` should NOT appear as untracked-to-commit. If they do, add
> them to `.gitignore`.

## Step 5 — Set up Python and install dependencies

```bash
cd ~/Projects/call-center-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

(You can instead run the helper `setup_mac.sh` from this folder, which does
steps 5 + scaffolds `.env` for you.)

## Step 6 — Run it locally

```bash
source .venv/bin/activate
python daily_fresh.py
# or, if the Flask object is named `app`:
#   gunicorn daily_fresh:app
```

Open `http://127.0.0.1:5000/` (or your health route) to confirm it boots.

## Step 7 — Verify

- App starts with no missing-env errors.
- Google Sheets read works (products load).
- A test WhatsApp message gets a reply (if pointing at the live webhook).
- **TEST LANGUAGE DETECTION:** Arabic in → Arabic out, English in → English
  out, no mid-conversation switching.

---

## Notes

- **Railway deployment is unaffected.** It deploys from GitHub, not from your
  computer — moving your dev machine doesn't change production. You keep pushing
  with `git push` from the Mac exactly as before.
- **Line endings:** Windows uses CRLF, Mac uses LF. Python doesn't care, but if
  git shows the whole file as "changed," run:
  `git config --global core.autocrlf input`
- **File paths:** if any code has hard-coded `C:\...\` Windows paths, switch them
  to relative paths or `os.path.join(...)`. Search the repo for `C:\\` and
  `\\` backslash paths.
- Set your git identity on the Mac once:
  `git config --global user.name "Muzafar"` and
  `git config --global user.email "muzafarj110@gmail.com"`

Want me to scan your `daily_fresh.py` for any hard-coded Windows paths once you
paste/upload it?
