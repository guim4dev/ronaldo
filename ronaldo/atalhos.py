"""Configured voice shortcuts that deliver a command to a named Hex terminal."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata

_lock = threading.Lock()
BOUNDARY = " ,.;:!?—-"


def _normalizar(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if unicodedata.category(c) != "Mn")


def casar(texto: str, atalhos):
    for atalho in atalhos:
        i = 0
        while i < len(texto) and (texto[i].isspace() or unicodedata.category(texto[i]).startswith("P")):
            i += 1
        if _normalizar(texto[i:i + 7]) == "ronaldo" and (i + 7 == len(texto) or texto[i + 7].isspace() or unicodedata.category(texto[i + 7]).startswith("P")):
            i += 7
            while i < len(texto) and (texto[i].isspace() or unicodedata.category(texto[i]).startswith("P")):
                i += 1
        for palavra in atalho["palavras"]:
            end = i + len(palavra)
            if _normalizar(texto[i:end]) == _normalizar(palavra) and (end == len(texto) or texto[end].isspace() or texto[end] in BOUNDARY):
                return atalho, re.sub(r"^[\s,.;:!?—]+", "", texto[end:])
    return None


def _call(path, args):
    hc = shutil.which("hc", path=path)
    if not hc:
        raise FileNotFoundError("hc")
    return subprocess.run([hc, *args], capture_output=True, text=True, timeout=10, env={**os.environ, "PATH": path})


def _failure(name, reason, uncertain=False):
    msg = f"entrega incerta ao {name}: {reason}" if uncertain else reason
    return "falhou", msg


def entregar_terminal(nome_terminal, resto, path="/usr/bin:/bin", timeout=10, nome=None):
    nome = nome or nome_terminal
    if not resto.strip():
        return _failure(nome, f"nada pra mandar ao {nome}")
    with _lock:
        sent_dispatched = False
        try:
            before = _call(path, ["get", nome_terminal, "--json"])
            if before.returncode:
                return _failure(nome, before.stderr.strip() or before.stdout.strip() or f"{nome} não está de pé")
            info = json.loads(before.stdout)
            status, labels = info.get("status", {}), info.get("labels", {})
            if info.get("state") != "live" or status.get("app") != "claude-code" or labels.get("reino.batuqueiro") != "1":
                return _failure(nome, f"{nome} não está de pé")
            addr, turn_before = info["address"], int(info["turn"])
            state = status.get("state")
            if state == "blocked":
                return _failure(nome, f"{nome} está esperando uma resposta (diálogo) — não mandei")
            if state not in ("working", "done", "idle"):
                return _failure(nome, f"{nome} não está de pé")
            if state in ("done", "idle"):
                keys = _call(path, ["keys", addr, "ctrl+u", "--json"])
                if keys.returncode:
                    return _failure(nome, keys.stderr.strip() or keys.stdout.strip() or "hc keys ctrl+u falhou")
            sent_dispatched = True
            sent = _call(path, ["send", addr, resto, "--json"])
            if sent.returncode:
                return _failure(nome, sent.stderr.strip() or sent.stdout.strip() or "hc send falhou", uncertain=True)
            try:
                result = json.loads(sent.stdout)
                started = result["started"]
            except (ValueError, TypeError, KeyError) as exc:
                return _failure(nome, f"resposta inválida de hc send: {exc}", uncertain=True)
            if started is False and state in ("done", "idle"):
                enter = _call(path, ["keys", addr, "enter", "--json"])
                if enter.returncode:
                    return _failure(nome, enter.stderr.strip() or enter.stdout.strip() or "hc keys enter falhou", uncertain=True)
            deadline = time.monotonic() + min(timeout, 3)
            while time.monotonic() < deadline:
                check = _call(path, ["get", addr, "--json"])
                if check.returncode:
                    return _failure(nome, check.stderr.strip() or check.stdout.strip() or "falha ao confirmar", uncertain=True)
                now = json.loads(check.stdout)
                if int(now.get("turn", 0)) > turn_before:
                    return "entregue", f"Entregue ao {nome}."
                time.sleep(0.2)
            return "sem_confirmacao", f"Enviado ao {nome}, sem confirmação"
        except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError) as exc:
            reason = str(exc) or type(exc).__name__
            if sent_dispatched:
                return _failure(nome, reason, uncertain=True)
            return _failure(nome, reason)
