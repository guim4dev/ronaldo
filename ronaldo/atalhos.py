"""Configured voice shortcuts that deliver a command to a named Hex terminal."""
from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass

_lock = threading.Lock()
BOUNDARY = " ,.;:!?—-"


def _normalizar(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if unicodedata.category(c) != "Mn")


def casar(texto: str, atalhos):
    for atalho in atalhos:
        s = texto
        i = 0
        while i < len(s) and (s[i].isspace() or unicodedata.category(s[i]).startswith("P")):
            i += 1
        if _normalizar(s[i:i+7]) == "ronaldo" and (i+7 == len(s) or s[i+7].isspace() or unicodedata.category(s[i+7]).startswith("P")):
            i += 7
            while i < len(s) and (s[i].isspace() or unicodedata.category(s[i]).startswith("P")):
                i += 1
        for palavra in atalho["palavras"]:
            token = s[i:i+len(palavra)]
            end = i + len(palavra)
            if _normalizar(token) == _normalizar(palavra) and (end == len(s) or s[end].isspace() or s[end] in BOUNDARY):
                resto = s[end:]
                resto = re.sub(r"^[\s,.;:!?—]+", "", resto)
                return atalho, resto
    return None


def _call(path, args):
    hc = shutil.which("hc", path=path)
    if not hc:
        raise FileNotFoundError("hc")
    return subprocess.run([hc, *args], capture_output=True, text=True, timeout=10, env={**os.environ, "PATH": path})


def entregar_terminal(nome_terminal, resto, path="/usr/bin:/bin", timeout=10):
    if not resto.strip():
        return False, "nada pra mandar ao batuqueiro"
    with _lock:
        try:
            before = _call(path, ["get", nome_terminal, "--json"])
            if before.returncode:
                return False, before.stderr.strip() or before.stdout.strip() or "batuqueiro não está de pé"
            info = json.loads(before.stdout)
            status = info.get("status", {})
            labels = info.get("labels", {})
            if info.get("state") != "live" or status.get("app") != "claude-code" or labels.get("reino.batuqueiro") != "1":
                return False, "batuqueiro não está de pé"
            addr = info["address"]
            turn_before = int(status.get("turn", 0))
            state = status.get("state")
            if state == "blocked":
                return False, "batuqueiro está esperando uma resposta (diálogo) — não mandei"
            if state not in ("working", "done", "idle"):
                return False, "batuqueiro não está de pé"
            if state in ("done", "idle"):
                keys = _call(path, ["keys", addr, "ctrl+u", "--json"])
                if keys.returncode:
                    return False, keys.stderr.strip() or keys.stdout.strip()
            sent_started = False
            try:
                sent = _call(path, ["send", addr, resto, "--json"])
            except subprocess.TimeoutExpired:
                return False, "entrega incerta ao batuqueiro (timeout após envio)"
            sent_started = True
            if sent.returncode:
                return False, sent.stderr.strip() or sent.stdout.strip()
            try:
                result = json.loads(sent.stdout)
                if "started" not in result:
                    raise ValueError("started ausente")
            except (ValueError, TypeError) as exc:
                return False, f"resposta inválida de hc send: {exc}"
            if result["started"] is False and state in ("done", "idle"):
                enter = _call(path, ["keys", addr, "enter", "--json"])
                if enter.returncode:
                    return False, enter.stderr.strip() or enter.stdout.strip()
            deadline = time.monotonic() + min(timeout, 3)
            while time.monotonic() < deadline:
                try:
                    check = _call(path, ["get", addr, "--json"])
                    if check.returncode == 0:
                        now = json.loads(check.stdout).get("status", {})
                        if now.get("state") == "working" or int(now.get("turn", 0)) > turn_before:
                            return True, "Entregue ao batuqueiro."
                except (subprocess.TimeoutExpired, ValueError, TypeError):
                    pass
            return True, "Enviado ao batuqueiro, sem confirmação"
        except subprocess.TimeoutExpired:
            return False, "timeout ao consultar batuqueiro"
        except FileNotFoundError:
            return False, "comando hc não encontrado"
        except (ValueError, KeyError, TypeError) as exc:
            return False, f"resposta inválida de hc: {exc}"
