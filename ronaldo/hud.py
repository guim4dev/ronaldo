"""Persistent non-activating floating feedback panel."""
from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger("ronaldo.hud")
_SCRIPT = Path(__file__).with_name("hud.js")
_STATE = Path.home() / "Library" / "Caches" / "ronaldo" / "hud.json"
_ACTION = _STATE.with_name("hud-action.json")
_FRAME = _STATE.with_name("hud-frame.json")
_lock = threading.RLock()
_seq = 0
_n = 0
_daemon: subprocess.Popen | None = None


def begin() -> int:
    global _seq
    with _lock:
        _seq += 1
        return _seq


def _write_state(payload: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="hud-", suffix=".tmp", dir=_STATE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as state_file:
            json.dump(payload, state_file, ensure_ascii=False)
            state_file.flush()
            os.fsync(state_file.fileno())
        os.replace(name, _STATE)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def start() -> None:
    global _daemon
    try:
        with _lock:
            if _daemon is not None and _daemon.poll() is None:
                return
            if _daemon is not None:
                try:
                    _daemon.wait(timeout=0)
                except Exception:
                    pass
            _STATE.parent.mkdir(parents=True, exist_ok=True)
            for caminho in (_STATE, _ACTION, _FRAME):
                try:
                    caminho.unlink()
                except FileNotFoundError:
                    pass
            _daemon = subprocess.Popen(
                [
                    "osascript",
                    "-l",
                    "JavaScript",
                    str(_SCRIPT),
                    str(_STATE),
                    str(_ACTION),
                    str(_FRAME),
                ],
                stdout=subprocess.DEVNULL,
                stderr=sys.stderr,
            )
    except Exception:
        log.exception("não foi possível iniciar daemon do HUD")


def stop() -> None:
    global _daemon
    try:
        with _lock:
            proc, _daemon = _daemon, None
            if proc is None:
                return
            try:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
            except Exception:
                log.exception("erro encerrando daemon do HUD")
    except Exception:
        log.exception("erro encerrando HUD")


atexit.register(stop)


def show(
    title: str,
    body: str,
    kind: str = "info",
    seconds: float = 6,
    req_id: int | None = None,
    cancel: bool = False,
) -> None:
    global _n
    try:
        with _lock:
            if req_id is not None and req_id != _seq:
                return
            start()
            if _daemon is None or _daemon.poll() is not None:
                return
            _n += 1
            payload = {
                "id": req_id if req_id is not None else begin(),
                "n": _n,
                "title": title,
                "body": body,
                "kind": kind,
                "seconds": seconds,
            }
            if cancel:
                payload["cancel"] = True
            _write_state(payload)
    except Exception:
        log.exception("não foi possível mostrar HUD")


def _read_json(path: Path) -> dict | None:
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


def _clear(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def read_action() -> dict | None:
    """The click the HUD reports, if any. Missing or broken files read as None."""
    return _read_json(_ACTION)


def clear_action() -> None:
    _clear(_ACTION)


def read_frame() -> dict | None:
    """The pill rectangle written by the HUD, in Quartz coordinates."""
    return _read_json(_FRAME)


def clear_frame() -> None:
    _clear(_FRAME)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print(
            "uso: python -m ronaldo.hud <titulo> <corpo> [kind] [segundos]",
            file=sys.stderr,
        )
        return 2
    title, body = args[:2]
    kind = args[2] if len(args) > 2 else "info"
    seconds = float(args[3]) if len(args) > 3 else 6
    start()
    show(title, body, kind, seconds)
    time.sleep(seconds + 1)
    stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
