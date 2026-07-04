#!/usr/bin/env bash
# Stop and remove the Switcher AC LaunchAgents. Leaves the AC in whatever
# state it's currently in (does NOT turn it off).
#
# Usage:  daemon/uninstall.sh
set -euo pipefail

LA="$HOME/Library/LaunchAgents"

for label in com.ayal.switcher-ac com.ayal.switcher-menubar; do
    plist="$LA/$label.plist"
    if [ -f "$plist" ]; then
        echo "==> Unloading $label"
        launchctl unload "$plist" 2>/dev/null || true
        rm -f "$plist"
    fi
done

echo "Removed. (The AC was left as-is — turn it off manually if you want.)"
