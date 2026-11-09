"""Drive the running Hex app through its bundled CLI (docs: `hex --help`)."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
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


def ensure_running(timeout: float = 45, cancel=None) -> bool:
    """Start Hex if it isn't running and wait until it can dictate.

    With `cancel`, stop waiting as soon as it returns true; the start probe runs
    in a thread so the wait does not depend on the CLI answering.
    """
    if _ready(status()):
        return True
    if cancel is not None and cancel():
        return False
    log.info("Hex não está pronto; iniciando")

    def iniciar() -> None:
        try:
            _run("start", timeout=timeout)
        except Exception:  # noqa: BLE001 - the poll below decides the result
            log.exception("falha ao iniciar o Hex")

    threading.Thread(target=iniciar, name="hex-start", daemon=True).start()
    deadline = time.monotonic() + timeout
    proximo = 0.0
    while time.monotonic() < deadline:
        if cancel is not None and cancel():
            return False
        if time.monotonic() >= proximo:
            if _ready(status()):
                return True
            proximo = time.monotonic() + 1.0
        time.sleep(0.1)
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
