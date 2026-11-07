"""`ronaldo on|off|status`: turn Ronaldo and the microphone off and back on.

Ronaldo and Hex both keep the microphone open, so `off` stops both. The
LaunchAgent restarts a killed listener, so `off` also disables the service, and
turns off Hex's launch at login: logging in again does not bring either back.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

LABEL = "dev.guima.ronaldo"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
HEX = "/Applications/Hex.app/Contents/MacOS/hex"
USO = "uso: ronaldo on|off|status"


def _run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _wait(condition, seconds: float = 10, step: float = 0.2) -> None:
    deadline = time.monotonic() + seconds
    while condition() and time.monotonic() < deadline:
        time.sleep(step)


def servico_carregado() -> bool:
    return _run("launchctl", "print", f"{_domain()}/{LABEL}").returncode == 0


def servico_desativado() -> bool:
    out = _run("launchctl", "print-disabled", _domain()).stdout
    return f'"{LABEL}" => disabled' in out


def hex_rodando() -> bool:
    return _run(HEX, "status", "--json").returncode == 0


def estado() -> str:
    ronaldo = "ligado" if servico_carregado() else "desligado"
    if servico_desativado():
        ronaldo += " (não sobe no login)"
    hexapp = "ligado" if hex_rodando() else "desligado"
    return f"ronaldo: {ronaldo}\nhex: {hexapp}"


def desligar() -> bool:
    """Stop the listener and Hex. False when Hex refused to quit (a dictation in progress)."""
    _run("launchctl", "disable", f"{_domain()}/{LABEL}")
    _run("launchctl", "bootout", f"{_domain()}/{LABEL}")
    _wait(servico_carregado)  # bootout returns before the process has exited
    if not hex_rodando():
        return True
    _run(HEX, "launch-at-login", "off")
    if _run(HEX, "quit").returncode != 0:
        return False
    _wait(hex_rodando)  # quit returns before Hex has exited
    return True


def ligar() -> bool:
    """Start Hex and the listener. False when Ronaldo isn't installed."""
    if not PLIST.exists() or not Path(HEX).exists():
        return False
    _run(HEX, "start")
    _run(HEX, "launch-at-login", "on")
    _run("launchctl", "enable", f"{_domain()}/{LABEL}")
    if not servico_carregado():
        _run("launchctl", "bootstrap", _domain(), str(PLIST))
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    comando = args[0] if args else "status"
    if comando == "on":
        if not ligar():
            print("Ronaldo não está instalado: rode ./install.sh", file=sys.stderr)
            return 1
    elif comando == "off":
        if not desligar():
            print("O Hex está ditando e continua aberto; rode ronaldo off de novo.", file=sys.stderr)
            print(estado())
            return 1
    elif comando != "status":
        print(USO, file=sys.stderr)
        return 2
    print(estado())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
