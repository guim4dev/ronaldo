"""Configured voice shortcuts: a short phrase runs a local command, or the rest of the phrase goes to a command that takes {text}."""
from __future__ import annotations

import os
import re
import subprocess
import unicodedata

BOUNDARY = " ,.;:!?—-"
MAX_PALAVRAS_COMANDO = 5  # atalho sem {text} só vale em fala curta
TIMEOUT_ENCAMINHO = 15.0  # atalho com {text} roda esperando, com este teto
PLACEHOLDER = "{text}"


def _normalizar(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if unicodedata.category(c) != "Mn")


def _esticada(palavra: str) -> re.Pattern:
    """Palavra que casa também esticada: 'gol' casa 'goool', 'golaço' casa 'golaaaço' (cada letra pode repetir)."""
    return re.compile("".join(re.escape(c) + "+" for c in _normalizar(palavra)))


def tem_texto(comando: list[str]) -> bool:
    """O comando recebe o resto da frase no lugar de {text}."""
    return any(PLACEHOLDER in argumento for argumento in comando)


def casar(texto: str, atalhos):
    for atalho in atalhos:
        i = 0
        while i < len(texto) and (texto[i].isspace() or unicodedata.category(texto[i]).startswith("P")):
            i += 1
        if _normalizar(texto[i:i + 7]) == "ronaldo" and (i + 7 == len(texto) or texto[i + 7].isspace() or unicodedata.category(texto[i + 7]).startswith("P")):
            i += 7
            while i < len(texto) and (texto[i].isspace() or unicodedata.category(texto[i]).startswith("P")):
                i += 1
        if not tem_texto(atalho["comando"]):
            limite = atalho.get("max_palavras", MAX_PALAVRAS_COMANDO)
            if len(re.findall(r"\w+", texto[i:])) > limite:
                continue
        if atalho.get("qualquer_posicao"):
            if any(_esticada(p).fullmatch(w) for w in re.findall(r"\w+", _normalizar(texto[i:])) for p in atalho["palavras"]):
                return atalho, ""
            continue
        for palavra in atalho["palavras"]:
            end = i + len(palavra)
            if _normalizar(texto[i:end]) == _normalizar(palavra) and (end == len(texto) or texto[end].isspace() or texto[end] in BOUNDARY):
                return atalho, re.sub(r"^[\s,.;:!?—]+", "", texto[end:])
    return None


def executar_comando(argv, path="/usr/bin:/bin", nome="atalho"):
    """Roda o comando curto sem esperar (ex.: afplay de um arquivo); ~ é expandido em cada argumento."""
    argv = [os.path.expanduser(a) for a in argv]
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, env={**os.environ, "PATH": path}, cwd=os.path.expanduser("~"))
    except (OSError, ValueError) as exc:
        return "falhou", f"{nome}: {exc}"
    return "entregue", f"Tocou {nome}." if os.path.basename(argv[0]) == "afplay" else f"Rodou {nome}."


def _primeira_linha(texto: str) -> str:
    for linha in texto.splitlines():
        if linha.strip():
            return linha.strip()
    return ""


def encaminhar(argv, resto, path="/usr/bin:/bin", timeout=TIMEOUT_ENCAMINHO, nome="atalho"):
    """Manda o resto da frase no lugar de {text}, espera e traduz o código de saída.

    Saída 0 = entregue; 75 = sem confirmação; outra = falhou. A 1ª linha do
    stdout (stderr na falha) é a mensagem do HUD.
    """
    if not resto.strip():
        return "falhou", f"nada pra mandar ao {nome}"
    resto = resto.strip()
    argv = [os.path.expanduser(a).replace(PLACEHOLDER, resto) for a in argv]
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "PATH": path}, cwd=os.path.expanduser("~"))
    except FileNotFoundError:
        return "falhou", f"{nome}: comando não encontrado: {argv[0]}"
    except subprocess.TimeoutExpired:
        return "sem_confirmacao", f"{nome} não respondeu em {timeout:.0f}s; entrega incerta"
    except OSError as exc:
        return "falhou", f"{nome}: {exc}"
    if r.returncode == 0:
        return "entregue", _primeira_linha(r.stdout) or f"Entregue ao {nome}."
    if r.returncode == 75:
        return "sem_confirmacao", _primeira_linha(r.stdout) or f"Enviado ao {nome}, sem confirmação"
    detalhe = _primeira_linha(r.stderr) or _primeira_linha(r.stdout) or f"{nome} saiu com código {r.returncode}"
    return "falhou", detalhe
