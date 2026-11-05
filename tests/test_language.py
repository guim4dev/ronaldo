"""Ronaldo keeps Hex transcribing in the user's language."""

import json
import subprocess

from ronaldo import hexcli
from ronaldo.listener import Config, system_language


def test_auto_language_follows_macos(monkeypatch):
    monkeypatch.setattr("ronaldo.listener._apple_languages", lambda: ["pt-BR", "en-US"])
    assert system_language() == "pt"
    assert Config(language="auto").resolved_language() == "pt"


def test_explicit_language_wins(monkeypatch):
    monkeypatch.setattr("ronaldo.listener._apple_languages", lambda: ["pt-BR"])
    assert Config(language="en").resolved_language() == "en"


def _fake_hex(language, calls):
    def run(*args, timeout=15):
        calls.append(args)
        out = json.dumps({"model": {"id": "parakeet_v3", "language": language}}) if args[0] == "status" else ""
        return subprocess.CompletedProcess(args, 0, out, "")

    return run


def test_switches_hex_language_when_it_drifted(monkeypatch):
    calls = []
    monkeypatch.setattr(hexcli, "_run", _fake_hex("en", calls))
    assert hexcli.ensure_language("pt") is True
    assert ("model", "use", "parakeet_v3", "--language", "pt") in calls


def test_leaves_hex_alone_when_language_matches(monkeypatch):
    calls = []
    monkeypatch.setattr(hexcli, "_run", _fake_hex("pt", calls))
    assert hexcli.ensure_language("pt") is True
    assert not any(c[0] == "model" for c in calls)
