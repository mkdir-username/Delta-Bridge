#!/usr/bin/env bash
# IoE — Internet over Email
# Usage: ./start.sh [port]
set -e

PORT="${1:-8080}"
DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE=""

# Auto-pull (silent, 10s timeout — fails gracefully under WL)
if [ -d "$DIR/.git" ]; then
  cd "$DIR"
  if timeout 10 git pull --ff-only origin main 2>/dev/null; then
    echo "[ioe] updated to $(git log --oneline -1 2>/dev/null)"
  fi
fi

# Find .env file
for f in "$DIR/.env" "$DIR/webui/.env" "$HOME/.ioe.env"; do
  [ -f "$f" ] && ENV_FILE="$f" && break
done

if [ -z "$ENV_FILE" ]; then
  echo "No .env file found. Create one with:"
  echo ""
  echo "  EMAIL=your@yandex.ru"
  echo "  IMAP_PASSWORD=your_app_password"
  echo "  IOE_SECRET=your_shared_secret"
  echo ""
  echo "Save as: $DIR/.env"
  exit 1
fi

# Load env
set -a
source "$ENV_FILE"
set +a

# Activate venv if present
if [ -f "$DIR/.venv/bin/activate" ]; then
  source "$DIR/.venv/bin/activate"
fi

# Check deps
python3 -c "from Crypto.Cipher import AES; from imapclient import IMAPClient; import pyotp" 2>/dev/null || {
  if [ -z "$VIRTUAL_ENV" ]; then
    echo "Dependencies missing. Activate venv first: source .venv/bin/activate"
    exit 1
  fi
  echo "Installing dependencies..."
  pip3 install pycryptodome imapclient pyotp qrcode bcrypt
}

# Find ioe_web.py
WEB="$DIR/webui/ioe_web.py"
[ -f "$WEB" ] || WEB="$DIR/client/ioe_web.py"
[ -f "$WEB" ] || WEB="$HOME/ioe_web.py"
[ -f "$WEB" ] || { echo "ioe_web.py not found"; exit 1; }

WEBDIR="$(dirname "$WEB")"
export PYTHONPATH="$DIR:${PYTHONPATH:-}"

# Claude proxy mode
if [ "$1" = "--claude" ] || [ "$1" = "claude" ]; then
  CLAUDE_PORT="${2:-8090}"
  PROXY="$DIR/client/claude_proxy.py"
  [ -f "$PROXY" ] || { echo "claude_proxy.py not found"; exit 1; }

  pkill -f "claude_proxy.py" 2>/dev/null || true
  sleep 1

  echo "Starting Claude IoE proxy on http://localhost:$CLAUDE_PORT"
  echo "Usage: ANTHROPIC_BASE_URL=http://localhost:$CLAUDE_PORT claude"
  cd "$DIR/client"
  exec python3 claude_proxy.py
fi

# Kill previous instance
pkill -f "ioe_web.py" 2>/dev/null || true
sleep 1

echo "Starting IoE on http://localhost:$PORT"
cd "$WEBDIR"
exec python3 ioe_web.py "$PORT"
