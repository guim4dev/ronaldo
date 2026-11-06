"""Hand a transcript to an external agent command and push its reply as a notification."""

from __future__ import annotations

import logging
import os
import subprocess
import threading

log = logging.getLogger("ronaldo.agent")

PLACEHOLDER = "{text}"
NOTIFY_CHARS = 240


def login_path() -> str:
    """The user's login-shell PATH: launchd starts us with /usr/bin:/bin only."""
    shell = os.environ.get("SHELL", "/bin/zsh")
    try:
        out = subprocess.run([shell, "-lc", 'printf %s "$PATH"'], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    return out.strip() or os.environ.get("PATH", "/usr/bin:/bin")


def build_argv(template: list[str], text: str) -> tuple[list[str], str | None]:
    """Replace {text} in the argv; without a placeholder the text goes to stdin."""
    if any(PLACEHOLDER in a for a in template):
        return [a.replace(PLACEHOLDER, text) for a in template], None
    return list(template), text


def notify(message: str, title: str = "Ronaldo") -> None:
    # Pass values as argv so nothing in the agent's reply is interpreted as AppleScript.
    script = ["-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)", "-e", "end run"]
    subprocess.run(["osascript", *script, message, title], capture_output=True, timeout=10)


def summarize(output: str) -> str:
    text = " ".join(output.split())
    return text if len(text) <= NOTIFY_CHARS else text[: NOTIFY_CHARS - 1] + "…"


def run(template: list[str], text: str, *, path: str, timeout: float, notify_reply: bool, name: str, hud: bool = False, req_id: int | None = None) -> tuple[bool, str]:
    """Run the agent command to completion (call from a worker thread)."""
    argv, stdin = build_argv(template, text)
    env = {**os.environ, "PATH": path, "RONALDO_TEXT": text}
    log.info("[%s] enviando para %s", name, argv[0])
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout, env=env, cwd=os.path.expanduser("~"))
        ok, output = r.returncode == 0, (r.stdout.strip() or r.stderr.strip())
        error_detail = r.stderr.strip() or r.stdout.strip()
        reply = output if ok else f"O agente falhou (código {r.returncode}): {output}"
    except FileNotFoundError:
        ok, output = False, ""
        error_detail = f"Comando não encontrado: {argv[0]}"
        reply = error_detail
    except subprocess.TimeoutExpired:
        ok, output = False, ""
        error_detail = f"O agente não respondeu em {timeout:.0f}s"
        reply = error_detail
    log.info("[%s] %s: %s", name, "ok" if ok else "falhou", reply)
    if notify_reply or not ok:  # failures always surface, even on silent routes
        try:
            notify(summarize(reply) or "Feito.", title=f"Ronaldo · {name}")
        except (OSError, subprocess.SubprocessError):
            log.exception("[%s] falha ao enviar notificação", name)
    if hud:
        from . import hud as hud_module
        if ok:
            hud_module.show("✅ " + summarize(output or "Entregue."), text, "ok", 6, req_id)
        else:
            hud_module.show("❌ Não entregou", summarize(error_detail or reply), "err", 12, req_id)
    return ok, reply


def dispatch(template: list[str], text: str, **kw) -> threading.Thread:
    """Fire and forget: the listener keeps listening while the agent works."""
    t = threading.Thread(target=run, args=(template, text), kwargs=kw, daemon=True)
    t.start()
    return t
