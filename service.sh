#!/bin/sh
# Run the planner in the background at login (macOS LaunchAgent).
#   ./service.sh install     start now and at every login
#   ./service.sh uninstall   stop and remove
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="local.weekly-planner"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

stop() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
}

case "${1:-}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-u</string>
    <string>$DIR/planner.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/planner.log</string>
  <key>StandardErrorPath</key><string>$DIR/planner.log</string>
</dict>
</plist>
EOF
    stop
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "Installed. Planner: http://localhost:4747/"
    ;;
  uninstall)
    stop
    rm -f "$PLIST"
    echo "Removed."
    ;;
  *)
    echo "usage: $0 install|uninstall" >&2
    exit 1
    ;;
esac
