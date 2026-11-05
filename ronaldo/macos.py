"""Tiny macOS helpers: clipboard via pbcopy/pbpaste, keystrokes via CoreGraphics (ctypes).

No pyobjc on purpose: loading AppKit/Quartz bindings costs tens of MB of RAM
for what amounts to three C calls.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import subprocess
import time

_cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
_cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
_cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
_cf.CFRelease.argtypes = [ctypes.c_void_p]

_HID_TAP = 0
_CMD = 1 << 20
KEY_V = 9
KEY_RETURN = 36

_UTF8 = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}


def press(key: int, flags: int = 0) -> None:
    for down in (True, False):
        ev = _cg.CGEventCreateKeyboardEvent(None, key, down)
        _cg.CGEventSetFlags(ev, flags)
        _cg.CGEventPost(_HID_TAP, ev)
        _cf.CFRelease(ev)
        time.sleep(0.01)


def get_clipboard() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, env=_UTF8).stdout.decode("utf-8", "replace")


def set_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=_UTF8, check=True)


def type_and_submit(text: str, submit: bool = True) -> None:
    """Paste `text` into the focused app, press Return, then restore the clipboard."""
    previous = get_clipboard()
    set_clipboard(text)
    time.sleep(0.05)
    press(KEY_V, _CMD)
    time.sleep(0.25)  # let the target app consume the paste before Return
    if submit:
        press(KEY_RETURN)
    time.sleep(0.3)
    if previous:  # pbpaste only sees text; don't clobber an image with ""
        set_clipboard(previous)


def is_trusted_for_accessibility() -> bool:
    ax = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    ax.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(ax.AXIsProcessTrusted())
