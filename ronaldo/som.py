"""Som local disparado por uma rota `som`: um processo de áudio próprio.

Diferente do `voz.Player`, este player não é interrompido pela wake word do
modo voz: quem para o som é o início de um ditado (`SomPlayer.stop`). O handle
do processo fica guardado para que o Falador saiba que há som tocando.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading

log = logging.getLogger("ronaldo.som")

PATH_PADRAO = "/usr/bin:/bin"


class SomPlayer:
    """Um processo de som por vez, guardado para poder ser parado."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    def tocar(self, argv: list[str], *, path: str = PATH_PADRAO, nome: str = "som") -> bool:
        """Roda o comando sem esperar; `~` é expandido em cada argumento."""
        argv = [os.path.expanduser(a) for a in argv]
        if not argv:
            return False
        self.stop()
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env={**os.environ, "PATH": path},
                cwd=os.path.expanduser("~"),
            )
        except (OSError, ValueError) as exc:
            log.warning("som: não consegui tocar %s: %s", nome, exc)
            return False
        with self._lock:
            self._proc = proc
        log.info("som: tocando %s (%s)", nome, argv[0])
        return True

    def tocando(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None or proc.poll() is not None:
            return
        log.info("som: parando áudio")
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


_PADRAO: SomPlayer | None = None
_PADRAO_LOCK = threading.Lock()


def padrao() -> SomPlayer:
    """O player usado pelo Listener e consultado pelo Falador."""
    global _PADRAO
    with _PADRAO_LOCK:
        if _PADRAO is None:
            _PADRAO = SomPlayer()
        return _PADRAO


def tocando() -> bool:
    return padrao().tocando()


def stop() -> None:
    padrao().stop()
