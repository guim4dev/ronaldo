#!/usr/bin/env bash
# Stops Ronaldo and removes the LaunchAgent and app. Leaves Hex settings and your config alone.
set -euo pipefail
APP="$HOME/Applications/Ronaldo.app"
INFO="$APP/Contents/Info.plist"
LABEL="${RONALDO_LABEL:-}"
if [[ -z "$LABEL" && -f "$INFO" ]]; then
  if [[ -x /usr/libexec/PlistBuddy ]]; then
    LABEL="$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$INFO" 2>/dev/null || true)"
  elif command -v plutil >/dev/null; then
    LABEL="$(plutil -extract CFBundleIdentifier raw -o - "$INFO" 2>/dev/null || true)"
  fi
fi
LABEL="${LABEL:-io.github.ronaldo}"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$APP"
echo "Ronaldo removido. (Config em ~/.config/ronaldo e logs em ~/Library/Logs/ronaldo.log ficaram.)"
