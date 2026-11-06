"""Non-activating floating feedback panel for dictation and agent replies."""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("ronaldo.hud")
_SCRIPT = Path(__file__).with_name("hud.js")
_lock = threading.Lock()
_seq = 0
_current: subprocess.Popen | None = None

def begin() -> int:
    global _seq
    with _lock:
        _seq += 1
        return _seq

def _reap(proc: subprocess.Popen, seconds: float) -> None:
    try:
        try:
            proc.wait(timeout=max(0, seconds) + 5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
    except Exception:
        log.exception("erro coletando processo do HUD")

def show(title: str, body: str, kind: str = "info", seconds: float = 6, req_id: int | None = None) -> None:
    global _current
    try:
        with _lock:
            if req_id is not None and req_id != _seq:
                return
            previous = _current
            if previous is not None:
                try:
                    previous.terminate()
                    try:
                        previous.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        previous.kill()
                        previous.wait(timeout=1)
                except Exception:
                    log.exception("erro encerrando HUD anterior")
                _current = None
            proc = subprocess.Popen(["osascript", "-l", "JavaScript", str(_SCRIPT), title, body, kind, str(seconds)], stdout=subprocess.DEVNULL, stderr=sys.stderr)
            _current = proc
            threading.Thread(target=_reap, args=(proc, seconds), daemon=True).start()
    except Exception:
        log.exception("não foi possível mostrar HUD")

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("uso: python -m ronaldo.hud <titulo> <corpo> [kind] [segundos]", file=sys.stderr)
        return 2
    title, body = args[:2]
    kind = args[2] if len(args) > 2 else "info"
    seconds = float(args[3]) if len(args) > 3 else 6
    show(title, body, kind, seconds)
    with _lock:
        proc = _current
    if proc is not None:
        try:
            proc.wait(timeout=seconds + 7)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=1)
            except Exception:
                log.exception("erro encerrando HUD manual")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
