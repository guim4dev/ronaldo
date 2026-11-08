#!/usr/bin/env bash
# Installs Ronaldo: builds ~/Applications/Ronaldo.app, registers a LaunchAgent so it
# starts at login (and restarts if it dies), and turns on Hex's launch-at-login.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/Ronaldo.app"
LABEL="${RONALDO_LABEL:-io.github.ronaldo}"  # o instalador de quem empacota o Ronaldo pode fixar outro
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/ronaldo.log"
HEX="/Applications/Hex.app/Contents/MacOS/hex"

[[ -x "$HEX" ]] || { echo "Hex não encontrado em /Applications/Hex.app: brew install --cask anomalyco/tap/hex" >&2; exit 1; }
# The archived Swift Hex (com.kitlangton.Hex) has no hex CLI, but its "Hex" binary
# passes the check above on a case-insensitive disk. Only the Rust app (anomaly.hex) works.
BUNDLE_ID="$(defaults read /Applications/Hex.app/Contents/Info CFBundleIdentifier 2>/dev/null || true)"
[[ "$BUNDLE_ID" == anomaly.hex ]] || {
  echo "/Applications/Hex.app é o Hex antigo em Swift ($BUNDLE_ID), sem o CLI hex." >&2
  echo "Troque pelo atual: brew uninstall --cask kitlangton-hex && brew install --cask anomalyco/tap/hex" >&2
  exit 1
}
command -v uv >/dev/null || { echo "precisa do uv: brew install uv" >&2; exit 1; }

echo "→ dependências"
(cd "$ROOT" && uv sync --quiet)
PY="$ROOT/.venv/bin/python"

echo "→ CLIs ronaldo e ronaldo-voz em ~/.local/bin"
mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/.venv/bin/ronaldo" "$HOME/.local/bin/ronaldo"
ln -sf "$ROOT/.venv/bin/ronaldo-voz" "$HOME/.local/bin/ronaldo-voz"
# The commands are on PATH only if the user's shell has ~/.local/bin there; it
# isn't by default on macOS. Ask the login shell, the one a new terminal runs.
case ":$("${SHELL:-/bin/zsh}" -ilc 'printf %s "$PATH"' 2>/dev/null):" in
  *":$HOME/.local/bin:"*) ;;
  *)
    case "${SHELL:-/bin/zsh}" in */bash) RC="~/.bashrc" ;; *) RC="~/.zshrc" ;; esac
    echo "  ~/.local/bin não está no PATH. Para usar ronaldo e ronaldo-voz, adicione ao $RC:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
    ;;
esac

echo "→ construindo $APP"
mkdir -p "$APP/Contents/MacOS"
clang -O2 -o "$APP/Contents/MacOS/Ronaldo" \
  -DRONALDO_PYTHON="\"$PY\"" -DRONALDO_ROOT="\"$ROOT\"" "$ROOT/macos/launcher.c"
sed "s/__LABEL__/$LABEL/" "$ROOT/macos/Info.plist" > "$APP/Contents/Info.plist"
codesign --force --sign - "$APP" >/dev/null 2>&1

echo "→ LaunchAgent $PLIST"
mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$APP/Contents/MacOS/Ronaldo</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLISTEOF

echo "→ Hex abre no login"
"$HEX" launch-at-login on >/dev/null

echo "→ (re)iniciando"
# "ronaldo off" disables the service; a disabled service refuses bootstrap.
launchctl enable "gui/$(id -u)/$LABEL"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
# bootout returns before the old instance has exited, and until it has, bootstrap
# fails with "Bootstrap failed: 5: Input/output error". Wait up to 10 s for it.
for _ in $(seq 50); do
  launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break
  sleep 0.2
done
launchctl bootstrap "gui/$(id -u)" "$PLIST"

cat <<MSG

Pronto. Logs: $LOG

Na primeira vez o macOS pede duas permissões para "Ronaldo":
  • Microfone: aparece um pop-up, clique em Permitir.
  • Acessibilidade (para colar e dar Enter): Ajustes do Sistema → Privacidade e Segurança →
    Acessibilidade → ative "Ronaldo" (se não aparecer, clique em + e escolha $APP).
Depois de dar a permissão: launchctl kickstart -k gui/\$(id -u)/$LABEL
MSG
