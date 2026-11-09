"""Cancel state for one dictation, shared by the listener, the CLI and the HUD.

No signals and no pidfile: `ronaldo cancel` writes a request file, a watcher
turns it into a cancel, and a worker stops the speech outside the lock. The
global hotkey only sets two events, so it never does I/O.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from . import hud, voz

log = logging.getLogger("ronaldo.cancelar")

REQUEST = Path.home() / "Library" / "Caches" / "ronaldo" / "cancel.request"
CLAIM = REQUEST.with_name("cancel.claim")
IDADE_MAXIMA = 10.0  # a request older than this is a leftover, not a cancel
INTERVALO = 0.2  # how often the watcher looks at the request file

_lock = threading.Lock()  # guards _armado, _id and _evento
_threads_lock = threading.Lock()
_evento = threading.Event()
_fala = threading.Event()
_armado = False
_id: int | None = None
_frame: tuple[float, float, float, float] | None = None
_parar = threading.Event()
_vigia: threading.Thread | None = None
_operario: threading.Thread | None = None


def armar(req_id: int | None) -> None:
    """Open a cancel window for this dictation, dropping any prior request."""
    global _armado, _id, _frame
    hud.clear_frame()
    with _lock:
        _evento.clear()
        _fala.clear()
        _frame = None
        _id = req_id
        _armado = True


def desarmar() -> None:
    """Close the window. A pending request to stop the speech is kept."""
    global _armado, _id, _frame
    with _lock:
        _armado = False
        _id = None
        _evento.clear()
        _frame = None
    hud.clear_frame()


def armado() -> bool:
    return _armado


def pedido() -> bool:
    return _evento.is_set()


def pedir() -> None:
    """Ask for a cancel. No I/O and no blocking: safe from the tap callback."""
    with _lock:
        if _armado:
            _evento.set()
        _fala.set()


def fechar() -> bool:
    """The atomic once of the send: True means the window is closed and clear."""
    global _armado, _id, _frame
    with _lock:
        if _evento.is_set():
            return False
        _armado = False
        _id = None
        _frame = None
        return True


def frame() -> tuple[float, float, float, float] | None:
    with _lock:
        return _frame


def dentro(x: float, y: float) -> bool:
    """Is the point inside the HUD pill, in Quartz coordinates (y from the top)?"""
    with _lock:
        retangulo = _frame
    if retangulo is None:
        return False
    fx, fy, largura, altura = retangulo
    return fx <= x <= fx + largura and fy <= y <= fy + altura


def _numero(valor: object) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return float(valor)


def atualizar_frame() -> None:
    """Cache the pill rectangle written by the HUD; the tap only reads numbers."""
    global _frame
    if not armado():
        return
    dados = hud.read_frame()
    if not isinstance(dados, dict):
        return
    x = _numero(dados.get("x"))
    y = _numero(dados.get("y"))
    w = _numero(dados.get("w"))
    h = _numero(dados.get("h"))
    if None in (x, y, w, h):
        return
    with _lock:
        if not _armado or dados.get("id") != _id:  # desarmou ou trocou o ditado durante o I/O
            return
        _frame = (x, y, w, h)


def verificar_pedido(agora: float | None = None) -> bool:
    """One watcher pass: claim the request file, turn a fresh one into a cancel.

    The claim is an atomic rename, so a `ronaldo cancel` that writes a new
    request at the same time lands in REQUEST and is not deleted by this pass.
    """
    momento = time.time() if agora is None else agora
    try:
        os.replace(REQUEST, CLAIM)
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("não consegui pegar o pedido de cancelamento: %s", exc)
        return False
    try:
        try:
            idade = momento - CLAIM.stat().st_mtime
        except OSError:
            return False
        if idade > IDADE_MAXIMA:
            log.info("pedido de cancelamento velho (%.0f s); ignorado", idade)
            return False
        pedir()
        return True
    finally:
        try:
            CLAIM.unlink()
        except OSError:
            pass


def _vigiar() -> None:
    while not _parar.is_set():
        try:
            verificar_pedido()
        except Exception:  # noqa: BLE001 - the watcher must not die
            log.exception("falha ao verificar o pedido de cancelamento")
        _parar.wait(INTERVALO)


def _trabalhar() -> None:
    while not _parar.is_set():
        if _fala.wait(INTERVALO):
            _fala.clear()
            try:
                voz.parar()
            except Exception:  # noqa: BLE001 - the worker must not die
                log.exception("falha ao parar a fala")


def iniciar() -> None:
    """Start (or renew) the watcher and the speech worker once."""
    global _vigia, _operario
    with _threads_lock:
        vigia_vivo = _vigia is not None and _vigia.is_alive()
        operario_vivo = _operario is not None and _operario.is_alive()
        if vigia_vivo and operario_vivo:
            return
        _parar.clear()
        if not vigia_vivo:
            _vigia = threading.Thread(target=_vigiar, name="ronaldo-cancelar-vigia", daemon=True)
            _vigia.start()
        if not operario_vivo:
            _operario = threading.Thread(target=_trabalhar, name="ronaldo-cancelar-fala", daemon=True)
            _operario.start()


def parar() -> None:
    """Stop both threads. Idempotent."""
    global _vigia, _operario
    with _threads_lock:
        _parar.set()
        vigia, operario = _vigia, _operario
        _vigia = _operario = None
    for fio in (vigia, operario):
        if fio is not None and fio is not threading.current_thread():
            fio.join(timeout=1)
