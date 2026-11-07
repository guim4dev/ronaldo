"""Test environment stubs.

The development box for this repository is Linux, but Ronaldo runs on macOS:
`sounddevice` needs PortAudio and `ronaldo.macos` needs CoreGraphics. When those
imports are unavailable we install inert stand-ins so collection can proceed.
Tests that exercise the real code replace the module under test explicitly.
"""

from __future__ import annotations

import sys
import types

import pytest


def _stub(name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


try:  # pragma: no cover - depends on the machine, not on the code
    import sounddevice  # noqa: F401
except Exception:  # noqa: BLE001 - anything means PortAudio is unavailable
    _stub("sounddevice", InputStream=type("InputStream", (), {}))

try:  # pragma: no cover - depends on the machine, not on the code
    import ronaldo.macos  # noqa: F401
except Exception:  # noqa: BLE001 - anything means CoreGraphics is unavailable

    def _noop(*_args, **_kwargs):
        return None

    module = _stub(
        "ronaldo.macos",
        press=_noop,
        get_clipboard=lambda: "",
        set_clipboard=_noop,
        type_and_submit=_noop,
        is_trusted_for_accessibility=lambda: True,
    )
    import ronaldo

    ronaldo.macos = module


@pytest.fixture(autouse=True)
def _linux_apple_languages(monkeypatch):
    """`defaults read -g AppleLanguages` only exists on macOS."""
    if sys.platform == "darwin":
        return
    from ronaldo import listener

    monkeypatch.setattr(listener, "_apple_languages", lambda: ["pt-BR"])
