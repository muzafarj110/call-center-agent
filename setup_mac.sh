#!/usr/bin/env bash
#
# setup_mac.sh — set up the Call Center Agent project on a Mac.
# Run AFTER cloning the repo:
#   cd ~/Projects/call-center-agent
#   bash setup_mac.sh
#
set -e

echo "==> Call Center Agent — Mac setup"

# 1. Python 3 ---------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 not found."
  echo "   Install it with Homebrew:  brew install python"
  echo "   (Install Homebrew first from https://brew.sh if you don't have it.)"
  exit 1
fi
PYV=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
echo "✓ python3 $PYV"

# 2. Git --------------------------------------------------------------------
if ! command -v git >/dev/null 2>&1; then
  echo "⚠️  git not found. Install with: xcode-select --install"
fi

# 3. Virtual environment ----------------------------------------------------
if [ ! -d ".venv" ]; then
  echo "==> Creating virtual environment (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "✓ virtualenv active: $(which python)"

# 4. Dependencies -----------------------------------------------------------
python -m pip install --upgrade pip >/dev/null
if [ -f requirements.txt ]; then
  echo "==> Installing requirements.txt"
  pip install -r requirements.txt
else
  echo "⚠️  No requirements.txt found in this folder."
fi

# 5. Secrets scaffold -------------------------------------------------------
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "✓ Created .env from .env.example — now fill in your real keys."
fi

echo ""
echo "==> NEXT STEPS"
echo "  1. Copy your secrets from the Windows PC into this folder:"
echo "       .env              (API keys, tokens)"
echo "       credentials.json  (Google service-account JSON)"
echo "     These are NOT in git, so they must be transferred manually."
echo "  2. Activate the env in new terminals:   source .venv/bin/activate"
echo "  3. Find the entry file (e.g. daily_fresh.py) and run it:"
echo "       python daily_fresh.py        # dev"
echo "     or  gunicorn daily_fresh:app   # if app object is named 'app'"
echo "  4. Test in browser / curl:   http://127.0.0.1:5000/health"
echo ""
echo "  ⚠️  After it runs, TEST LANGUAGE DETECTION:"
echo "      Arabic in -> Arabic out, English in -> English out."
echo ""
echo "✅ Setup complete."
