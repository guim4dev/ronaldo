#!/usr/bin/env python3
"""Pecas comuns do treino e da avaliacao do `gol_grito`.

Contrato (o mesmo de `ronaldo/detector.py`): uma janela e [16, 96] float32
(16 embeddings de 96 dimensoes, 80 ms por embedding = 2 s) e o classificador
devolve um score por janela. Nada aqui toca audio em disco: so features.

O que mora neste modulo:

- `sessao_onnx` / `scores_janelas`: rodar o classificador exportado em lote,
  com as mesmas janelas que o detector monta chunk a chunk;
- `segmentos_do_meta` / `scores_stream`: pontuar um stream de avaliacao por
  chunk, sem criar janelas que atravessem a fronteira de dois arquivos;
- `contar_disparos`: intervalo minimo de 8 s (100 chunks) entre disparos;
- `limite_poisson`: limite superior unilateral de 95% para a FA/h;
- `chunk_nivel` / `preparar_portao` / `portao_libera_grito`: portao de
  volume simulado com a MESMA classe de producao (`ronaldo.grito.PortaoGrito`),
  alimentado com o RMS dBFS gravado por chunk.

Aproximacoes documentadas (ver `RESULTADOS.md`):

- streams nao tem audio, so o RMS dBFS de cada chunk: o chunk sintetico tem
  amplitude constante e o mesmo RMS (o portao so olha o RMS);
- VAD aproximado por `rms > piso_do_arquivo + 10 dB`, com o piso do arquivo
  sendo o percentil 10 do RMS daquele arquivo;
- o primeiro chunk de cada arquivo de stream e um stream novo: o portao
  recalibra e as 15 primeiras janelas (historico incompleto) sao descartadas.
"""

from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path

import numpy as np

CHUNK = 1280
SR = 16000
JANELA = 16
DIM = 96
PASSO_S = CHUNK / SR  # 0,08 s
CHUNKS_8S = int(round(8.0 / PASSO_S))  # 100
SILENCIO_DB = -100.0

log = logging.getLogger("gol.modelo")


# --------------------------------------------------------------------------- #
# ONNX
# --------------------------------------------------------------------------- #
def sessao_onnx(caminho: Path | str, threads: int = 1):
    """Sessao com as mesmas opcoes de ronaldo/detector._session."""
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.enable_cpu_mem_arena = False
    opts.log_severity_level = 3
    return ort.InferenceSession(str(caminho), sess_options=opts, providers=["CPUExecutionProvider"])


def scores_janelas(sessao, janelas: np.ndarray, lote: int = 4096) -> np.ndarray:
    """[N, 16, 96] -> [N] float32.

    O modelo exportado tem lote fixo 1 (como o `ronaldo_ptbr.onnx`): nesse caso
    roda uma janela por chamada, que e exatamente o caminho de producao. Se o
    modelo aceitar lote dinamico, aproveita o lote.
    """
    nome = sessao.get_inputs()[0].name
    forma = sessao.get_inputs()[0].shape
    lote_fixo = bool(forma and isinstance(forma[0], int) and forma[0] == 1)
    x = np.asarray(janelas, dtype=np.float32)
    saida = np.empty(len(x), dtype=np.float32)
    if lote_fixo:
        for i in range(len(x)):
            y = sessao.run(None, {nome: np.ascontiguousarray(x[i : i + 1])})[0]
            saida[i] = np.asarray(y, dtype=np.float32).reshape(-1)[0]
        return saida
    for i in range(0, len(x), lote):
        pedaco = np.ascontiguousarray(x[i : i + lote])
        y = np.asarray(sessao.run(None, {nome: pedaco})[0], dtype=np.float32).reshape(-1)
        saida[i : i + len(pedaco)] = y
    return saida


# --------------------------------------------------------------------------- #
# streams
# --------------------------------------------------------------------------- #
def segmentos_do_meta(meta: dict, dados: Path | str, categoria_bruta: str) -> list[tuple[int, int]]:
    """Fronteiras (inicio, fim) em chunks de cada arquivo do stream.

    O conversor grava um `_features.npy` concatenando os arquivos; uma janela
    que atravessa dois arquivos nao existe na producao. As fronteiras saem da
    duracao de cada wav bruto (`frames // 1280`, igual a features.py). Se algum
    wav faltar ou a soma nao bater, cai para um segmento unico e avisa.
    """
    import soundfile as sf

    pasta = Path(dados) / "raw" / categoria_bruta / "wav"
    contagens = []
    for nome in meta.get("arquivos", []):
        caminho = pasta / nome
        if not caminho.exists():
            log.warning("stream %s: %s sumiu; usando um segmento unico", categoria_bruta, caminho)
            return [(0, int(meta["chunks"]))]
        info = sf.info(str(caminho))
        contagens.append(int(info.frames) // CHUNK)
    total = sum(contagens)
    if total != int(meta["chunks"]):
        log.warning(
            "stream %s: soma dos arquivos %d != meta %d; usando um segmento unico",
            categoria_bruta,
            total,
            meta["chunks"],
        )
        return [(0, int(meta["chunks"]))]
    limites = np.cumsum([0] + contagens).astype(np.int64)
    return [(int(a), int(b)) for a, b in zip(limites[:-1], limites[1:]) if b > a]


def iter_janelas(feats, segmentos: list[tuple[int, int]], lote: int = 8192):
    """Gera (indice_do_chunk, [n, 16, 96]) com janelas completas por segmento.

    `indice_do_chunk` e o indice do chunk final da janela (o mesmo chunk que o
    detector pontua). As 15 primeiras janelas de cada segmento sao puladas: o
    historico anterior pertence a outro arquivo (ou nao existe).
    """
    for ini, fim in segmentos:
        ini = max(0, int(ini))
        fim = min(int(fim), len(feats))
        inicio_janela = ini + JANELA - 1
        if fim <= inicio_janela:
            continue
        for a in range(inicio_janela, fim, lote):
            b = min(a + lote, fim)
            idx = np.arange(a, b)[:, None] + np.arange(-(JANELA - 1), 1)[None, :]
            yield a, np.asarray(feats[idx], dtype=np.float32)


def scores_stream(sessao, feats, segmentos: list[tuple[int, int]], lote: int = 8192):
    """Pontua o stream chunk a chunk; devolve (indices, scores)."""
    indices = []
    scores = []
    for a, janelas in iter_janelas(feats, segmentos, lote):
        y = scores_janelas(sessao, janelas)
        indices.append(np.arange(a, a + len(y), dtype=np.int64))
        scores.append(y)
    if not indices:
        return np.zeros(0, np.int64), np.zeros(0, np.float32)
    return np.concatenate(indices), np.concatenate(scores)


def contar_disparos(indices, scores, limiar: float, chunks_min: int = CHUNKS_8S) -> list[int]:
    """Disparos com intervalo minimo de `chunks_min` (8 s = 100 chunks)."""
    disparos: list[int] = []
    ultimo = None
    for i, s in zip(indices, scores):
        if float(s) < limiar:
            continue
        if ultimo is not None and int(i) - ultimo < chunks_min:
            continue
        disparos.append(int(i))
        ultimo = int(i)
    return disparos


def limite_poisson(k: int, horas: float) -> float:
    """Limite superior unilateral de 95% para a taxa (Poisson); 0 -> ~3/T."""
    if horas <= 0:
        return float("nan")
    if k <= 0:
        return 3.0 / horas
    from scipy.stats import chi2

    return float(chi2.ppf(0.95, 2 * (k + 1)) / 2.0 / horas)


def fa_por_hora(k: int, horas: float) -> tuple[float, float]:
    """(taxa observada, limite superior 95%) em disparos/hora."""
    if horas <= 0:
        return float("nan"), float("nan")
    return k / horas, limite_poisson(k, horas)


# --------------------------------------------------------------------------- #
# porta de volume (simulado com a classe de producao)
# --------------------------------------------------------------------------- #
def carregar_portao():
    """Importa PortaoGrito de `ronaldo/grito.py` (o mesmo da producao).

    A branch de dados nasceu antes da Parte A; ate o merge, o arquivo pode
    estar num worktree irmao. Procura, nesta ordem: o proprio repo, os
    diretorios de `RONALDO_FONTES` (separados por `:`) e `../ronaldo-som`.
    """
    repo = Path(__file__).resolve().parents[2]
    candidatos = [repo]
    for item in os.environ.get("RONALDO_FONTES", "").split(os.pathsep):
        if item.strip():
            candidatos.append(Path(item).expanduser())
    candidatos.append(repo.parent / "ronaldo-som")
    vistos = set()
    for base in candidatos:
        base = base.resolve()
        if base in vistos or not (base / "ronaldo" / "grito.py").exists():
            continue
        vistos.add(base)
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        try:
            for nome in [m for m in sys.modules if m == "ronaldo" or m.startswith("ronaldo.")]:
                del sys.modules[nome]
            modulo = __import__("ronaldo.grito", fromlist=["PortaoGrito"])
            return modulo.PortaoGrito
        except Exception as erro:  # noqa: BLE001
            log.warning("PortaoGrito em %s nao carregou: %s", base, erro)
    raise SystemExit(
        "ronaldo/grito.py nao encontrado (PortaoGrito). Rode numa branch que tenha a Parte A "
        "ou aponte RONALDO_FONTES para um worktree com ronaldo/grito.py."
    )


_CHUNKS_NIVEL: dict[float, np.ndarray] = {}


def chunk_nivel(db: float) -> np.ndarray:
    """Chunk int16 de amplitude constante cujo RMS dBFS e exatamente `db`."""
    chave = round(float(db), 2)
    if chave not in _CHUNKS_NIVEL:
        amplitude = 32768.0 * (10.0 ** (chave / 20.0))
        inteiro = int(round(amplitude))
        inteiro = max(0, min(32767, inteiro)) if chave > SILENCIO_DB else 0
        _CHUNKS_NIVEL[chave] = np.full(CHUNK, inteiro, dtype=np.int16)
    return _CHUNKS_NIVEL[chave]


REFERENCIA_DB = -26.0  # fala normal simulada dos clipes (~0,05 de RMS)
GRIOT_ACIMA_DB = 12.0  # grito simulado: referencia + 12 dB
PORTAO_ACIMA_DB = 10.0  # o mesmo padrao da rota som
_PREPARO_CHUNKS = int(round(25.0 / PASSO_S))  # 25 s de fala para a referencia


def preparar_portao(PortaoGrito, referencia_db: float = REFERENCIA_DB):
    """Portao com referencia valida: 25 s de fala normal simulada."""
    portao = PortaoGrito()
    chunk = chunk_nivel(referencia_db)
    for _ in range(_PREPARO_CHUNKS):
        portao.observar(chunk, True)
    assert portao.referencia is not None
    return portao


def portao_libera_grito(portao, nota: float, acima_db: float = PORTAO_ACIMA_DB,
                        referencia_db: float = REFERENCIA_DB) -> bool:
    """Simula o pico do grito (referencia + 12 dB) e consulta o portao."""
    chunk = chunk_nivel(referencia_db + GRIOT_ACIMA_DB)
    for _ in range(13):  # janela de nivel: 13 chunks = ~1,0 s
        portao.observar(chunk, True)
    return bool(portao.avaliar(nota, acima_db).liberado)


def portao_libera_fala(portao, nota: float, acima_db: float = PORTAO_ACIMA_DB) -> bool:
    """Fala normal no nivel da referencia: o portao tem que barrar."""
    return bool(portao.avaliar(nota, acima_db).liberado)


# --------------------------------------------------------------------------- #
# FA/h de um stream com e sem portao
# --------------------------------------------------------------------------- #
def avaliar_stream(
    sessao,
    feats,
    rms,
    segmentos: list[tuple[int, int]],
    limiares: list[float],
    PortaoGrito=None,
    acima_db: float = PORTAO_ACIMA_DB,
) -> dict:
    """Disparos por limiar em um stream, com e sem o portao de volume.

    Sem portao: score >= limiar, com intervalo de 8 s.
    Com portao: cada chunk passa pelo `PortaoGrito` (RMS dBFS + VAD
    aproximado) e so conta o disparo liberado, tambem com 8 s.
    """
    indices, scores = scores_stream(sessao, feats, segmentos)
    n = len(indices)
    horas = n * PASSO_S / 3600.0
    resultado = {"chunks": int(n), "horas": round(horas, 4), "por_limiar": {}}
    if n == 0:
        for limiar in limiares:
            resultado["por_limiar"][limiar] = {
                "sem": {"disparos": 0, "fa_h": 0.0, "limite95": float("nan")},
                "com": {"disparos": 0, "fa_h": 0.0, "limite95": float("nan")},
            }
        return resultado

    for limiar in limiares:
        k = len(contar_disparos(indices, scores, limiar))
        taxa, limite = fa_por_hora(k, horas)
        resultado["por_limiar"][limiar] = {
            "sem": {"disparos": k, "fa_h": taxa, "limite95": limite},
            "com": {"disparos": 0, "fa_h": float("nan"), "limite95": float("nan")},
        }

    if PortaoGrito is None:
        return resultado

    # score por chunk (NaN nas janelas descartadas no inicio de cada segmento)
    score_chunk = np.full(len(feats), np.nan, dtype=np.float32)
    score_chunk[indices] = scores
    rms = np.asarray(rms, dtype=np.float32)
    limiares_ord = sorted(limiares, reverse=True)
    estado = {limiar: {"ultimo": None, "contagem": 0} for limiar in limiares}
    # Um portao por arquivo (stream novo = recalibra). O mesmo estado serve a
    # todos os limiares: `avaliar` nao altera o portao.
    for ini, fim in segmentos:
        ini, fim = max(0, int(ini)), min(int(fim), len(feats))
        trecho_rms = rms[ini:fim]
        piso = float(np.percentile(trecho_rms, 10)) if len(trecho_rms) else SILENCIO_DB
        corte_fala = piso + 10.0
        portao = PortaoGrito()
        for i in range(ini, fim):
            db = float(rms[i]) if i < len(rms) else SILENCIO_DB
            portao.observar(chunk_nivel(db), db > corte_fala)
            nota = score_chunk[i]
            if np.isnan(nota):
                continue
            nota = float(nota)
            for limiar in limiares_ord:
                if nota < limiar:
                    continue
                e = estado[limiar]
                if not portao.avaliar(nota, acima_db).liberado:
                    continue
                if e["ultimo"] is not None and i - e["ultimo"] < CHUNKS_8S:
                    continue
                e["ultimo"] = i
                e["contagem"] += 1
    for limiar in limiares:
        k = estado[limiar]["contagem"]
        taxa, limite = fa_por_hora(k, horas)
        resultado["por_limiar"][limiar]["com"] = {
            "disparos": k, "fa_h": taxa, "limite95": limite,
        }
    return resultado
