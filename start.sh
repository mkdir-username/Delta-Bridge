#!/usr/bin/env bash
# IoE — Internet over Email
# Usage: ./start.sh [port]
set -e

PORT="${1:-8080}"
DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE=""

# Auto-update from git if available
if [ -d "$DIR/.git" ]; then
  echo "Checking for updates..."
  cd "$DIR"
  if git fetch origin main --quiet 2>/dev/null; then
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)
    if [ "$LOCAL" != "$REMOTE" ]; then
      COUNT=$(git log --oneline "$LOCAL".."$REMOTE" | wc -l | tr -d ' ')
      echo "Updating $COUNT commits..."
      if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
        git reset --hard origin/main --quiet 2>/dev/null
      else
        git stash --quiet 2>/dev/null
        git reset --hard origin/main --quiet 2>/dev/null
        git stash pop --quiet 2>/dev/null || true
      fi
      echo "Updated to $(git log -1 --format='%h %s')"
    else
      echo "Already up to date."
    fi
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

# Check deps
python3 -c "from Crypto.Cipher import AES" 2>/dev/null || {
  echo "Installing pycryptodome..."
  pip3 install pycryptodome 2>/dev/null || pip3 install --break-system-packages pycryptodome
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
