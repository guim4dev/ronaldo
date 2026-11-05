#!/usr/bin/env bash
# Ronaldo route -> a long-lived agent living in its own Herdr workspace (https://herdr.dev).
#
# On first use (or after the agent exited) it creates a "Ronaldo" workspace in Herdr,
# starts the agent there under a fixed name, then submits the transcript as a prompt
# and returns at once. The agent keeps its context across requests and you can watch
# it in the Herdr app. Text comes from $RONALDO_TEXT (set by Ronaldo) or stdin.
#
# Usage in ~/.config/ronaldo/config.toml:
#   command = ["/path/to/herdr-agent.sh", "claude", "--dangerously-skip-permissions"]
#   (first arg = Herdr agent kind: claude, codex, hermes, opencode, ...; the rest are the agent's own args)
# Env: RONALDO_AGENT_NAME (default "ronaldo"), RONALDO_AGENT_CWD (default ~/Ronaldo),
#      RONALDO_WORKSPACE (Herdr workspace label, default "Ronaldo").
set -euo pipefail

NAME="${RONALDO_AGENT_NAME:-ronaldo}"
CWD="${RONALDO_AGENT_CWD:-$HOME/Ronaldo}"
LABEL="${RONALDO_WORKSPACE:-Ronaldo}"
TEXT="${RONALDO_TEXT:-$(cat)}"
[[ $# -ge 1 ]] || { echo "uso: herdr-agent.sh <kind> [args do agente...]" >&2; exit 2; }
[[ -n "$TEXT" ]] || { echo "texto vazio" >&2; exit 2; }
KIND="$1"; shift
mkdir -p "$CWD"
command -v herdr >/dev/null || { echo "herdr não está no PATH" >&2; exit 127; }
command -v jq >/dev/null || { echo "precisa do jq" >&2; exit 127; }

if ! herdr agent get "$NAME" >/dev/null 2>&1; then
  ws=$(herdr workspace list | jq -r --arg l "$LABEL" '.result.workspaces[] | select(.label == $l) | .workspace_id' | head -1)
  if [[ -z "$ws" ]]; then
    pane=$(herdr workspace create --label "$LABEL" --cwd "$CWD" --no-focus | jq -r '.result.root_pane.pane_id')
  else
    pane=$(herdr pane list --workspace "$ws" | jq -r '.result.panes[] | select(.agent == null) | .pane_id' | head -1)
    [[ -n "$pane" ]] || { echo "workspace $LABEL sem shell livre para iniciar o agente" >&2; exit 1; }
  fi
  if ! out=$(herdr agent start "$NAME" --kind "$KIND" --pane "$pane" --timeout 90000 -- "$@" 2>&1); then
    echo "o agente $NAME não ficou pronto (abra o workspace $LABEL no Herdr): $out" >&2
    exit 1
  fi
fi

# Rejected with agent_blocked if it's waiting on a dialog: Ronaldo pushes that as a failure.
herdr agent prompt "$NAME" "$TEXT" >/dev/null
