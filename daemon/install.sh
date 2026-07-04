#!/usr/bin/env bash
# Install the Switcher AC as macOS LaunchAgents so it runs at login and
# restarts on crash. Two agents:
#
#   com.ayal.switcher-ac        — the server + control loop, wrapped in
#                                 `caffeinate -is` so the Mac won't idle-sleep
#                                 while it's driving the AC. (single process)
#   com.ayal.switcher-menubar   — the menu-bar UI (GUI session)
#
# This supersedes the old free-running scripts (auto_cloud.py / ac_cycle.sh):
# it stops any of those it finds so you never get two controllers fighting.
#
# Usage:  daemon/install.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LA="$HOME/Library/LaunchAgents"
LOGS="$REPO/logs"

[ -x "$PY" ] || { echo "venv python not found at $PY — create the venv first."; exit 1; }
mkdir -p "$LA" "$LOGS"

echo "==> Stopping any old, un-managed controllers…"
launchctl unload "$LA/com.ayal.switcher-ac.plist" 2>/dev/null || true
launchctl unload "$LA/com.ayal.switcher-menubar.plist" 2>/dev/null || true
pkill -f 'ac_cycle.sh' 2>/dev/null || true
pkill -f '[a]uto_cloud.py' 2>/dev/null || true
pkill -f '[s]erver.py' 2>/dev/null || true
sleep 1

echo "==> Writing LaunchAgents…"

cat > "$LA/com.ayal.switcher-ac.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>            <string>com.ayal.switcher-ac</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-is</string>
        <string>$PY</string>
        <string>$REPO/server.py</string>
    </array>
    <key>WorkingDirectory</key>  <string>$REPO</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>    <string>$REPO/src</string>
    </dict>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <true/>
    <key>StandardOutPath</key>   <string>$LOGS/server.out.log</string>
    <key>StandardErrorPath</key> <string>$LOGS/server.err.log</string>
</dict>
</plist>
PLIST

cat > "$LA/com.ayal.switcher-menubar.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>            <string>com.ayal.switcher-menubar</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$REPO/menubar.py</string>
    </array>
    <key>WorkingDirectory</key>  <string>$REPO</string>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <true/>
    <key>StandardOutPath</key>   <string>$LOGS/menubar.out.log</string>
    <key>StandardErrorPath</key> <string>$LOGS/menubar.err.log</string>
</dict>
</plist>
PLIST

echo "==> Loading agents…"
launchctl load -w "$LA/com.ayal.switcher-ac.plist"
launchctl load -w "$LA/com.ayal.switcher-menubar.plist"

echo "Done. Server + loop on http://localhost:3001 , menu-bar app running."
echo "Logs: $LOGS/  ·  Uninstall: daemon/uninstall.sh"
