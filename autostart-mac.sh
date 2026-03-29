#!/usr/bin/env bash
# Install LaunchAgent for auto-start on macOS login
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.local.ioe-webui.plist"

cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.ioe-webui</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/start.sh</string>
    <string>8090</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/ioe-webui.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/ioe-webui.log</string>
</dict>
</plist>
EOF

launchctl load "$PLIST" 2>/dev/null || true
echo "Installed: IoE starts on login at http://localhost:8090"
echo "Uninstall: launchctl unload $PLIST && rm $PLIST"
