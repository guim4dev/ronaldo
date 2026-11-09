"""Global cancel shortcut on macOS through a CoreGraphics event tap.

The module imports on any platform; `iniciar` does nothing outside macOS. The
tap callback never touches the disk: it only reads numbers it already has and
sets events.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading

from . import cancelar

log = logging.getLogger("ronaldo.hotkey")

CMD = 1 << 20
SHIFT = 1 << 17
ALT = 1 << 19
CTRL = 1 << 18
_MODIFICADORES_TODOS = CMD | SHIFT | ALT | CTRL

_MODIFICADORES = {
    "cmd": CMD,
    "command": CMD,
    "shift": SHIFT,
    "alt": ALT,
    "option": ALT,
    "ctrl": CTRL,
    "control": CTRL,
}

# ANSI virtual key codes.
_TECLAS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25,
    "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33,
    "i": 34, "p": 35, "return": 36, "l": 37, "j": 38, "'": 39, "k": 40,
    ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "tab": 48, "space": 49, "escape": 53,
}

_ROTULO_MOD = {
    "cmd": "\u2318", "command": "\u2318", "shift": "\u21e7",
    "alt": "\u2325", "option": "\u2325", "ctrl": "\u2303", "control": "\u2303",
}
_ROTULO_TECLA = {"escape": "Esc", "space": "Space", "return": "\u21a9", "tab": "\u21e5"}

KEY_DOWN, KEY_UP = 10, 11
MOUSE_DOWN, MOUSE_UP = 1, 2
_DESABILITADO = (0xFFFFFFFE, 0xFFFFFFFF)
_CAMPO_TECLA = 9

# keyDown | keyUp | leftMouseDown | leftMouseUp
MASCARA = (1 << KEY_DOWN) | (1 << KEY_UP) | (1 << MOUSE_DOWN) | (1 << MOUSE_UP)


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


_TAP_CALLBACK = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p
)

_iniciado = False
_referencias: list[object] = []  # keeps the callback and the tap alive


def _partes(atalho: str) -> list[str] | None:
    if not isinstance(atalho, str) or not atalho.strip():
        return None
    partes = [parte.strip().lower() for parte in atalho.split("+")]
    if not all(partes):
        return None
    return partes


def parse(atalho: str) -> tuple[int, int] | None:
    """`cmd+d` -> (cmd flag, keycode). None when the shortcut is invalid."""
    partes = _partes(atalho)
    if partes is None:
        return None
    mods, tecla = partes[:-1], partes[-1]
    flags = 0
    for mod in mods:
        if mod not in _MODIFICADORES:
            return None
        flags |= _MODIFICADORES[mod]
    if tecla not in _TECLAS:
        return None
    return flags, _TECLAS[tecla]


def rotulo(atalho: str) -> str:
    """`cmd+d` -> `⌘D`, `escape` -> `Esc`; empty string when invalid."""
    if parse(atalho) is None:
        return ""
    partes = _partes(atalho) or []
    prefixo = "".join(_ROTULO_MOD[mod] for mod in partes[:-1])
    tecla = partes[-1]
    return prefixo + _ROTULO_TECLA.get(tecla, tecla.upper())


def _tratar(tipo: int, tecla: int | None, flags: int, ponto, estado: dict) -> bool:
    """Decide whether to swallow the event. Pure arithmetic: no I/O."""
    if tipo in (KEY_DOWN, KEY_UP):
        alvo_flags, alvo_tecla = estado["alvo"]
        if tecla != alvo_tecla or (flags & _MODIFICADORES_TODOS) != alvo_flags:
            return False
        if not estado["ativo"]():
            return False
        estado["pedir"]()
        return True
    if tipo in (MOUSE_DOWN, MOUSE_UP):
        if not estado["ativo"]():
            return False
        if ponto is None or not estado["dentro"](ponto[0], ponto[1]):
            return False
        estado["pedir"]()
        return True
    return False


def _responder(estado: dict, tipo: int, evento) -> bool:
    cg = estado["cg"]
    if tipo in _DESABILITADO:
        tap = estado.get("tap")
        if tap:
            cg.CGEventTapEnable(tap, True)
            log.warning("o tap do atalho caiu; reativado")
        return False
    if tipo in (KEY_DOWN, KEY_UP):
        tecla = int(cg.CGEventGetIntegerValueField(evento, _CAMPO_TECLA))
        flags = int(cg.CGEventGetFlags(evento))
        return _tratar(tipo, tecla, flags, None, estado)
    if tipo in (MOUSE_DOWN, MOUSE_UP):
        local = cg.CGEventGetLocation(evento)
        if local is None:
            return False
        return _tratar(tipo, None, 0, (float(local.x), float(local.y)), estado)
    return False


def _rodar_tap(estado: dict, cg, cf, callback) -> None:
    tap = cg.CGEventTapCreate(0, 0, 0, MASCARA, callback, None)
    if not tap:
        log.warning(
            "sem permissão de Acessibilidade: o atalho e o clique no HUD não funcionam; use ronaldo cancel"
        )
        return
    estado["tap"] = tap
    fonte = cf.CFMachPortCreateRunLoopSource(None, tap, 0)
    if not fonte:
        log.warning("não consegui criar a fonte do atalho")
        return
    modo = ctypes.c_void_p.in_dll(cf, "kCFRunLoopCommonModes").value
    cf.CFRunLoopAddSource(cf.CFRunLoopGetCurrent(), fonte, modo)
    cg.CGEventTapEnable(tap, True)
    _referencias.extend([tap, fonte, callback])
    cf.CFRunLoopRun()


def _instalar(alvo: tuple[int, int], pedir, ativo) -> None:
    global _iniciado
    if _iniciado:
        return
    _iniciado = True
    cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

    cg.CGEventTapCreate.restype = ctypes.c_void_p
    cg.CGEventTapCreate.argtypes = [
        ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint64, _TAP_CALLBACK, ctypes.c_void_p,
    ]
    cg.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    cg.CGEventGetIntegerValueField.restype = ctypes.c_int64
    cg.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    cg.CGEventGetFlags.restype = ctypes.c_uint64
    cg.CGEventGetFlags.argtypes = [ctypes.c_void_p]
    cg.CGEventGetLocation.restype = CGPoint
    cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
    cf.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
    cf.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32]
    cf.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    cf.CFRunLoopRun.argtypes = []

    estado: dict = {
        "alvo": alvo,
        "pedir": pedir,
        "ativo": ativo,
        "dentro": cancelar.dentro,
        "cg": cg,
        "tap": None,
    }

    def bruto(proxy, tipo, evento, info):
        try:
            engolir = _responder(estado, int(tipo), evento)
        except Exception:  # noqa: BLE001 - the callback must never break the tap
            log.exception("falha no atalho global")
            return evento
        return None if engolir else evento

    callback = _TAP_CALLBACK(bruto)
    threading.Thread(
        target=_rodar_tap, args=(estado, cg, cf, callback), name="ronaldo-atalho", daemon=True
    ).start()


def iniciar(atalho: str, pedir, ativo) -> None:
    """Install the global shortcut. `pedir` and `ativo` must be cheap and I/O free."""
    if sys.platform != "darwin":
        return
    alvo = parse(atalho)
    if alvo is None:
        log.warning("atalho de cancelamento inválido (%r); nenhum atalho ativo", atalho)
        return
    try:
        _instalar(alvo, pedir, ativo)
    except Exception:  # noqa: BLE001 - without the shortcut the rest still works
        log.exception("não consegui ativar o atalho global")
