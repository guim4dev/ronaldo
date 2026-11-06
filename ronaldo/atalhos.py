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


def _hc_error(result):
    raw = result.stderr.strip() or result.stdout.strip()
    try:
        error = json.loads(raw).get("error", {})
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    except (ValueError, AttributeError):
        pass
    return raw


def _decode_todo(raw):
    info = json.loads(raw)
    if not isinstance(info, dict):
        raise ValueError("resposta deve ser um objeto")
    if not isinstance(info.get("status"), dict):
        raise ValueError("status deve ser um objeto")
    if not isinstance(info.get("labels"), dict):
        raise ValueError("labels deve ser um objeto")
    if not isinstance(info.get("address"), str) or not info["address"]:
        raise ValueError("address deve ser uma string não vazia")
    turn = info.get("turn")
    if not isinstance(turn, int) or isinstance(turn, bool):
        raise ValueError("turn deve ser um inteiro")
    if "created_ms" not in info:
        raise ValueError("created_ms ausente")
    return info


def _invalid_instance(info, address, created_ms):
    return (info.get("address") != address or info.get("created_ms") != created_ms
            or info.get("state") != "live"
            or info["status"].get("app") != "claude-code"
            or info["labels"].get("reino.batuqueiro") != "1")


def entregar_terminal(nome_terminal, resto, path="/usr/bin:/bin", timeout=10, nome=None):
    nome = nome or nome_terminal
    if not resto.strip():
        return _failure(nome, f"nada pra mandar ao {nome}")
    with _lock:
        sent_dispatched = False
        try:
            before = _call(path, ["get", nome_terminal, "--json"])
            if before.returncode:
                return _failure(nome, _hc_error(before) or f"{nome} não está de pé")
            try:
                info = _decode_todo(before.stdout)
            except (ValueError, TypeError) as exc:
                return _failure(nome, f"resposta inválida de hc: {exc}")
            status, labels = info["status"], info["labels"]
            if info.get("state") != "live" or status.get("app") != "claude-code" or labels.get("reino.batuqueiro") != "1":
                return _failure(nome, f"{nome} não está de pé")
            addr, created_ms, turn_before = info["address"], info["created_ms"], info["turn"]
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
                return _failure(nome, _hc_error(sent) or "hc send falhou", uncertain=True)
            try:
                result = json.loads(sent.stdout)
                if not isinstance(result, dict):
                    raise ValueError("resposta deve ser um objeto")
                started = result["started"]
                if not isinstance(started, bool):
                    raise ValueError("started deve ser booleano")
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
                    return _failure(nome, _hc_error(check) or "falha ao confirmar", uncertain=True)
                try:
                    now = _decode_todo(check.stdout)
                except (ValueError, TypeError) as exc:
                    return _failure(nome, f"resposta inválida de hc: {exc}", uncertain=True)
                if _invalid_instance(now, addr, created_ms):
                    return _failure(nome, f"{nome} foi substituído durante a entrega", uncertain=True)
                if now["turn"] > turn_before:
                    if now["turn"] != turn_before + 1:
                        return _failure(nome, f"{nome} foi substituído durante a entrega", uncertain=True)
                    return "entregue", f"Entregue ao {nome}."
                time.sleep(0.2)
            return "sem_confirmacao", f"Enviado ao {nome}, sem confirmação"
        except Exception as exc:
            reason = str(exc) or type(exc).__name__
            if sent_dispatched:
                return _failure(nome, reason, uncertain=True)
            return _failure(nome, reason)
