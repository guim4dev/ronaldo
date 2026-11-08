"""`ronaldo on|off|status`: turn Ronaldo and the microphone off and back on.

Ronaldo and Hex both keep the microphone open, so `off` stops both. The
LaunchAgent restarts a killed listener, so `off` also disables the service, and
turns off Hex's launch at login. If Hex is already closed, `off` leaves it
closed to avoid opening the microphone, so its launch at login stays unchanged.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

PADRAO = "io.github.ronaldo"
ESPERA = 10.0
HEX = "/Applications/Hex.app/Contents/MacOS/hex"
USO = "uso: ronaldo on|off|status"


def _run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def app_info() -> Path:
    return Path.home() / "Applications" / "Ronaldo.app" / "Contents" / "Info.plist"


def label() -> str:
    """The LaunchAgent label: $RONALDO_LABEL, the app bundle id, or the default."""
    escolhido = os.environ.get("RONALDO_LABEL", "")
    if escolhido:
        return escolhido
    try:
        with open(app_info(), "rb") as arquivo:
            dados = plistlib.load(arquivo)
    except Exception:  # ausente, ilegível ou não é um plist: usa o padrão
        return PADRAO
    if isinstance(dados, dict) and isinstance(dados.get("CFBundleIdentifier"), str):
        return dados["CFBundleIdentifier"] or PADRAO
    return PADRAO


def plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label()}.plist"


def _wait(condition, seconds: float | None = None, step: float = 0.2) -> bool:
    """Wait until condition is false. True when it went false before the deadline."""
    deadline = time.monotonic() + (ESPERA if seconds is None else seconds)
    while condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(step)
    return True


def servico_carregado() -> bool:
    return _run("launchctl", "print", f"{_domain()}/{label()}").returncode == 0


def servico_desativado() -> bool:
    out = _run("launchctl", "print-disabled", _domain()).stdout
    return f'"{label()}" => disabled' in out


def hex_rodando() -> bool:
    return _run(HEX, "status", "--json").returncode == 0


def estado() -> str:
    ronaldo = "ligado" if servico_carregado() else "desligado"
    if servico_desativado():
        ronaldo += " (não sobe no login)"
    hexapp = "ligado" if hex_rodando() else "desligado"
    return f"ronaldo: {ronaldo}\nhex: {hexapp}"


def desligar() -> tuple[str | None, str | None]:
    """Stop the listener and Hex; return an error and an optional warning."""
    erro = None
    if _run("launchctl", "disable", f"{_domain()}/{label()}").returncode != 0:
        erro = "O Ronaldo não foi desativado; rode ronaldo off de novo."
    _run("launchctl", "bootout", f"{_domain()}/{label()}")
    if not _wait(servico_carregado):  # bootout returns before the process has exited
        if erro is None:
            erro = "O Ronaldo não parou a tempo; rode ronaldo off de novo."
    if not servico_desativado() and erro is None:
        erro = "O Ronaldo não foi desativado; rode ronaldo off de novo."
    if not hex_rodando():
        aviso = (
            "O Hex já estava fechado; a abertura dele no login não foi desligada. "
            "Se ele abrir no próximo login, rode ronaldo off de novo."
        )
        return erro, aviso
    if _run(HEX, "launch-at-login", "off").returncode != 0 and erro is None:
        erro = "O Hex continua abrindo no login; rode ronaldo off de novo."
    if _run(HEX, "quit").returncode != 0:
        return "O Hex está ditando e continua aberto; rode ronaldo off de novo.", None
    if not _wait(hex_rodando):  # quit returns before Hex has exited
        if erro is None:
            erro = "O Hex não parou a tempo; rode ronaldo off de novo."
    return erro, None


def ligar() -> str | None:
    """Start Hex and the listener. None on success, else why it failed."""
    if not plist().exists() or not Path(HEX).exists():
        return "Ronaldo não está instalado: rode ./install.sh"
    if _run(HEX, "start").returncode != 0:
        return "O Hex não abriu"
    if _run(HEX, "launch-at-login", "on").returncode != 0:
        return "O Hex não ativou a abertura no login"
    if _run("launchctl", "enable", f"{_domain()}/{label()}").returncode != 0:
        return "O Ronaldo não foi habilitado"
    if not servico_carregado():
        if _run("launchctl", "bootstrap", _domain(), str(plist())).returncode != 0:
            return "O Ronaldo não abriu"
    if not _wait(lambda: not servico_carregado()):
        return "O Ronaldo não ligou a tempo"
    if not hex_rodando():
        return "O Hex não ligou a tempo"
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    comando = args[0] if args else "status"
    if comando == "on":
        erro = ligar()
        if erro:
            print(erro, file=sys.stderr)
            print(estado())
            return 1
    elif comando == "off":
        erro, aviso = desligar()
        if aviso:
            print(aviso, file=sys.stderr)
        if erro:
            print(erro, file=sys.stderr)
            print(estado())
            return 1
    elif comando != "status":
        print(USO, file=sys.stderr)
        return 2
    print(estado())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
