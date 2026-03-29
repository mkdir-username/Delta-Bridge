#!/usr/bin/env bash
# IoE setup — run once after clone
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

# Install deps
echo "Installing dependencies..."
if command -v pkg >/dev/null 2>&1; then
  # Termux
  pkg install -y python 2>/dev/null || true
  pip install pycryptodome imapclient beautifulsoup4 2>/dev/null || true
else
  # macOS / Linux
  pip3 install pycryptodome 2>/dev/null || pip3 install --break-system-packages pycryptodome 2>/dev/null || true
fi

# Create .env if missing
if [ ! -f "$DIR/.env" ] && [ ! -f "$HOME/.ioe.env" ]; then
  echo ""
  echo "Create .env file with your IMAP credentials:"
  echo ""
  read -p "Email (yandex): " IOE_EMAIL
  read -p "IMAP app password: " IOE_PASS
  read -p "Shared secret (any random string): " IOE_SECRET
  cat > "$DIR/.env" << EOF
EMAIL=$IOE_EMAIL
IMAP_PASSWORD=$IOE_PASS
IOE_SECRET=$IOE_SECRET
EOF
  echo "Saved to $DIR/.env"
fi

# Add alias
SHELL_RC=""
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"
[ -f "$HOME/.bashrc" ] && SHELL_RC="$HOME/.bashrc"

if [ -n "$SHELL_RC" ]; then
  if ! grep -q "alias ioe=" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "alias ioe='$DIR/start.sh'" >> "$SHELL_RC"
    echo "Added 'ioe' alias to $SHELL_RC"
    echo "Run: source $SHELL_RC"
  else
    echo "'ioe' alias already exists"
  fi
fi

echo ""
echo "Setup complete. Run:"
echo "  ./start.sh        # default port 8080"
echo "  ./start.sh 8090   # custom port"
echo "  ioe               # after sourcing shell rc"
