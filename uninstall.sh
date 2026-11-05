#!/usr/bin/env bash
# Stops Ronaldo and removes the LaunchAgent and app. Leaves Hex settings and your config alone.
set -euo pipefail
LABEL="dev.guima.ronaldo"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Ronaldo.app"
echo "Ronaldo removido. (Config em ~/.config/ronaldo e logs em ~/Library/Logs/ronaldo.log ficaram.)"
