"""Drive the running Hex app through its bundled CLI (docs: `hex --help`)."""

from __future__ import annotations

import json
import logging
import subprocess
import time

log = logging.getLogger("ronaldo.hex")

HEX = "/Applications/Hex.app/Contents/MacOS/hex"
NOT_RUNNING = 3
NO_SPEECH = 4


def _run(*args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run([HEX, *args], capture_output=True, text=True, timeout=timeout)


def status() -> dict | None:
    r = _run("status", "--json")
    if r.returncode == NOT_RUNNING:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _ready(s: dict | None) -> bool:
    return bool(s and s.get("permissions", {}).get("ready") and s.get("model", {}).get("installed"))


def ensure_running(timeout: float = 45) -> bool:
    """Start Hex if it isn't running and wait until it can dictate."""
    if _ready(status()):
        return True
    log.info("Hex não está pronto; iniciando")
    _run("start", timeout=timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ready(status()):
            return True
        time.sleep(1)
    log.error("Hex não ficou pronto em %ss", timeout)
    return False


def ensure_language(language: str) -> bool:
    """Make Hex transcribe in `language` (e.g. "pt"), switching only if it drifted."""
    s = status()
    model = (s or {}).get("model") or {}
    if not model.get("id"):
        log.error("não consegui ler o modelo do Hex para conferir o idioma")
        return False
    if model.get("language") == language:
        return True
    log.info("Hex estava em '%s'; trocando para '%s'", model.get("language"), language)
    r = _run("model", "use", model["id"], "--language", language)
    if r.returncode != 0:
        log.error("hex model use falhou (%s): %s", r.returncode, (r.stderr or r.stdout).strip())
    return r.returncode == 0


def start_dictation() -> bool:
    r = _run("dictation", "start")
    if r.returncode != 0:
        log.error("hex dictation start falhou (%s): %s", r.returncode, (r.stderr or r.stdout).strip())
    return r.returncode == 0


def stop_and_transcribe(timeout: float = 120) -> str | None:
    """Stop recording and return the transcript, or None when nothing was said."""
    r = _run("dictation", "stop", "--print", timeout=timeout)
    if r.returncode == NO_SPEECH:
        return None
    if r.returncode != 0:
        log.error("hex dictation stop falhou (%s): %s", r.returncode, (r.stderr or r.stdout).strip())
        return None
    return r.stdout.strip() or None


def discard_dictation(timeout: float = 120) -> None:
    """Throw the recording away: nothing is typed, sent or spoken afterwards.

    `hex dictation cancel` discards the audio on Hex versions that have it; older
    ones stop and print the transcript, which is simply dropped here.
    """
    r = _run("dictation", "cancel", timeout=15)
    if r.returncode == 0:
        return
    log.info("hex dictation cancel indisponível (%s); parando e descartando", r.returncode)
    _run("dictation", "stop", "--print", timeout=timeout)
