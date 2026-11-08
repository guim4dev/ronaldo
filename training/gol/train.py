#!/usr/bin/env python3
"""Treina o classificador `gol_grito` (openWakeWord-compativel, entrada [1,16,96]).

Dados (nunca no git; ver DADOS.md e MANIFESTO.json em $GOL_DATA):

  features/pos_train.npy        gritos sinteticos de treino
  features/neg_train.npy        fala normal com "gol", palavras parecidas e palavras curtas gritadas
  features/stream_*_treino_*    conversa/jogo/musica de TREINO (nunca os de avaliacao)
  raw/openwakeword/openwakeword_features_ACAV100M_2000_hrs_16bit.npy  negativos gerais (mmap)
  raw/openwakeword/validation_set_features.npy                        FA/h de validacao

Escolha de checkpoint (early stop) usa SO:
  - recall no split de validacao de pos_train;
  - FA/h no validation_set_features.npy (com intervalo de 8 s).
pos_test e os streams de avaliacao NUNCA entram aqui.

Uso:
  uv run python train.py                        # treino de verdade (exige MANIFESTO.json)
  uv run python train.py --variacao b --lote-acav 512
  uv run python train.py --smoke --dados /tmp/gol-smoke --epocas 2   # prova rapida
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent.parent
for base in (AQUI, REPO):
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

import modelo as M  # noqa: E402

log = logging.getLogger("gol.train")

ACAV_NOME = "openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
VAL_NOME = "validation_set_features.npy"
CATEGORIAS = ("speech_ptbr", "game", "music")
LIMIARES = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


# --------------------------------------------------------------------------- #
# dados
# --------------------------------------------------------------------------- #
class AmostradorStream:
    """Sorteia janelas [16,96] dentro de um stream de treino (sem cruzar arquivos)."""

    def __init__(self, feats, segmentos: list[tuple[int, int]], nome: str = ""):
        self.feats = feats
        self.segmentos = [(a, b) for a, b in segmentos if b - a >= M.JANELA]
        self.nome = nome
        self.pesos = np.asarray([b - a - M.JANELA + 1 for a, b in self.segmentos], dtype=np.float64)
        if len(self.segmentos) == 0 or self.pesos.sum() <= 0:
            raise SystemExit(f"stream {nome}: sem segmentos uteis")
        self.pesos /= self.pesos.sum()

    def amostrar(self, n: int, rng: np.random.Generator) -> np.ndarray:
        saida = np.empty((n, M.JANELA, M.DIM), dtype=np.float32)
        escolhas = rng.choice(len(self.segmentos), size=n, p=self.pesos)
        for j, e in enumerate(escolhas):
            ini, fim = self.segmentos[int(e)]
            ultimo_inicio = fim - M.JANELA
            i = int(rng.integers(ini, ultimo_inicio + 1))
            saida[j] = self.feats[i : i + M.JANELA]
        return saida


# --------------------------------------------------------------------------- #
# positivos alinhados (janelas que a producao ve)
# --------------------------------------------------------------------------- #
class PositivosAlinhados:
    """Janelas de 16 embeddings com o fim da palavra em varios pontos.

    Regra (do cavaleiro): positiva so quando a palavra inteira (>= 80%) esta
    dentro da janela e o fim dela cai nos ultimos ~0,5 s da janela. Janelas
    antes da palavra sao negativas. Janelas parciais ficam de fora.

    A janela k cobre o audio de [(k-15)*0.08 - 0.68, (k+1)*0.08]: o contexto
    de mel de 76 frames se estende ~0,7 s para tras do primeiro embedding.
    """

    def __init__(self, stream, offsets, meta: dict, val_frac: float, seed: int):
        self.stream = stream
        self.offsets = np.asarray(offsets, dtype=np.int64)
        itens = meta["itens"]
        self.chunks = np.asarray([int(it["chunks"]) for it in itens], dtype=np.int64)
        self.inicio = np.asarray([float(it["inicio_chunk"]) for it in itens], dtype=np.float64)
        self.fim = np.asarray([float(it["fim_chunk"]) for it in itens], dtype=np.float64)
        self.positivas: list[list[int]] = []
        self.negativas: list[list[int]] = []
        for i in range(len(itens)):
            inicio_s = self.inicio[i] * M.PASSO_S
            fim_s = self.fim[i] * M.PASSO_S
            dur = max(fim_s - inicio_s, 1e-6)
            pos, neg = [], []
            for k in range(M.JANELA - 1, int(self.chunks[i])):
                s0 = (k - (M.JANELA - 1)) * M.PASSO_S - 0.68
                s1 = (k + 1) * M.PASSO_S
                if s1 < inicio_s:
                    neg.append(k)
                    continue
                if s1 < fim_s or (s1 - fim_s) > 0.5:
                    continue
                cobertura = (min(s1, fim_s) - max(s0, inicio_s)) / dur
                if cobertura >= 0.8:
                    pos.append(k)
            self.positivas.append(pos)
            self.negativas.append(neg)
        usaveis = [i for i in range(len(itens)) if self.positivas[i]]
        ordem = np.random.default_rng(seed).permutation(len(usaveis))
        n_val = max(1, int(round(len(usaveis) * val_frac)))
        self.val_idx = [usaveis[j] for j in ordem[:n_val]]
        self.treino_idx = [usaveis[j] for j in ordem[n_val:]]
        self.com_pos = [i for i in usaveis]
        self.com_neg = [i for i in range(len(itens)) if self.negativas[i]]
        self.e_real = np.asarray([it.get("origem") == "real" for it in itens], dtype=bool)
        self.real_treino = [i for i in self.treino_idx if self.e_real[i]]
        self.sint_treino = [i for i in self.treino_idx if not self.e_real[i]]
        log.info(
            "alinhado: %d clipes (%d com janela positiva, %d reais), val=%d, media pos=%.1f neg=%.1f",
            len(itens), len(usaveis), int(self.e_real.sum()), len(self.val_idx),
            float(np.mean([len(self.positivas[i]) for i in usaveis])),
            float(np.mean([len(self.negativas[i]) for i in self.com_neg])),
        )

    def _janela(self, i: int, k: int) -> np.ndarray:
        off = int(self.offsets[i])
        return np.asarray(self.stream[off + k - (M.JANELA - 1) : off + k + 1], dtype=np.float32)

    def amostrar(self, n: int, rng: np.random.Generator, frac_neg: float = 0.25,
                 frac_real: float = 0.0):
        xs, ys = [], []
        for _ in range(n):
            negativo = rng.random() < frac_neg
            if negativo and self.com_neg:
                i = self.com_neg[int(rng.integers(0, len(self.com_neg)))]
                ks = self.negativas[i]
                # prefere as janelas logo antes da palavra (mais dificeis)
                k = ks[max(0, len(ks) - 1 - int(rng.integers(0, min(5, len(ks)))))]
                ys.append(0.0)
            else:
                if self.real_treino and rng.random() < frac_real:
                    i = self.real_treino[int(rng.integers(0, len(self.real_treino)))]
                else:
                    base = self.sint_treino or self.treino_idx
                    i = base[int(rng.integers(0, len(base)))]
                ks = self.positivas[i]
                # prioriza a janela em que o fim da palavra cai no fim dela
                # (delay 0), que e o caso dos clipes de teste de 2 s
                pesos = np.exp(-np.arange(len(ks)) / 2.0)
                k = ks[int(rng.choice(len(ks), p=pesos / pesos.sum()))]
                ys.append(1.0)
            xs.append(self._janela(i, k))
        return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32)

    def scores_val(self, rede, lote: int = 8192) -> tuple[np.ndarray, np.ndarray]:
        """Max por chunk e ultima janela de cada clipe de validacao (torch)."""
        import torch

        maximo = np.zeros(len(self.val_idx), dtype=np.float32)
        ultima = np.zeros(len(self.val_idx), dtype=np.float32)
        pendentes, donos, tipos = [], [], []
        rede.eval()

        def drenar():
            if not pendentes:
                return
            with torch.no_grad():
                notas = rede(torch.from_numpy(np.asarray(pendentes, dtype=np.float32))).numpy().reshape(-1)
            for d, t, nota in zip(donos, tipos, notas):
                if t == "max":
                    maximo[d] = max(maximo[d], float(nota))
                else:
                    ultima[d] = float(nota)
            pendentes.clear(); donos.clear(); tipos.clear()

        for j, i in enumerate(self.val_idx):
            for k in range(M.JANELA - 1, int(self.chunks[i])):
                pendentes.append(self._janela(i, k)); donos.append(j); tipos.append("max")
                if len(pendentes) >= lote:
                    drenar()
            # janela em que o fim da palavra cai no fim dela (delay 0), que e
            # o caso dos clipes de teste com a palavra ate o fim do wav
            k_fim = max(M.JANELA - 1, min(int(self.chunks[i]) - 1,
                                          int(math.ceil(self.fim[i])) - 1))
            pendentes.append(self._janela(i, k_fim))
            donos.append(j); tipos.append("ultima")
        drenar()
        return maximo, ultima


def validar_fonte_publica(caminho: str | Path, nome: str = "fonte") -> Path:
    real = Path(os.path.realpath(Path(caminho).expanduser()))
    pasta = real if real.is_dir() else real.parent
    for ancestral in (pasta, *pasta.parents):
        marcador = ancestral / ".privado"
        if marcador.is_file():
            raise SystemExit(f"recusado {nome}: {real} fica sob o marcador privado {marcador}")
    return real


def validar_fontes_publicas(dados: Path) -> None:
    """Checa as fontes conhecidas antes de carregar qualquer dado de treino."""
    validar_fonte_publica(dados, "--dados")
    raizes = [
        dados / "features",
        dados / "raw" / "openwakeword",
        dados / "treino",
        *(dados / "raw" / nome / "wav" for nome in CATEGORIAS),
    ]
    for raiz in raizes:
        validar_fonte_publica(raiz, "fonte de treino")
        if not raiz.is_dir():
            continue
        for pasta, diretorios, arquivos in os.walk(raiz, followlinks=False):
            for nome in diretorios + arquivos:
                validar_fonte_publica(Path(pasta) / nome, "fonte de treino")


def _carregar_vetor(caminho: Path, mmap: bool = True,
                    permitir_privado: bool = False) -> np.ndarray:
    if not permitir_privado:
        validar_fonte_publica(caminho)
    if not caminho.exists():
        raise SystemExit(f"falta {caminho} (ver DADOS.md; espere o MANIFESTO.json)")
    return np.load(caminho, mmap_mode="r" if mmap else None)


def _split_real_por_video(nomes: list[str], videos: list[str], val_frac: float,
                          seed: int) -> tuple[np.ndarray, np.ndarray]:
    if not videos or len(nomes) == 0:
        raise SystemExit("real_split.json nao tem clipes e videos de treino")
    val_videos = set(str(v) for v in np.random.default_rng(seed).permutation(videos)[
                     :max(1, int(round(len(videos) * val_frac)))])
    ids = [re.sub(r"_\d+$", "", Path(nome).stem) for nome in nomes]
    treino = np.asarray([i for i, video in enumerate(ids) if video not in val_videos], dtype=np.int64)
    validacao = np.asarray([i for i, video in enumerate(ids) if video in val_videos], dtype=np.int64)
    if not len(treino) or not len(validacao):
        raise SystemExit("split por video de real_train deixou treino ou validacao vazio")
    return treino, validacao


def carregar_dados(dados: Path, val_frac: float, seed: int,
                   permitir_privado: bool = False) -> dict:
    feat = dados / "features"
    alinhado = None
    pos = None
    stream_p = feat / "pos_all_stream.npy"
    offsets_p = feat / "pos_all_offsets.npy"
    meta_p = feat / "pos_all_meta.json"
    if not stream_p.exists():
        stream_p = feat / "pos_v2_stream.npy"
        offsets_p = feat / "pos_v2_offsets.npy"
        meta_p = feat / "pos_v2_meta.json"
    if stream_p.exists() and offsets_p.exists() and meta_p.exists():
        if not permitir_privado:
            validar_fonte_publica(stream_p); validar_fonte_publica(offsets_p); validar_fonte_publica(meta_p)
        alinhado = PositivosAlinhados(
            np.load(stream_p, mmap_mode="r"), np.load(offsets_p),
            json.loads(meta_p.read_text(encoding="utf-8")), val_frac, seed,
        )
    if (feat / "pos_train.npy").exists():
        pos = _carregar_vetor(feat / "pos_train.npy", permitir_privado=permitir_privado)
    elif alinhado is None:
        raise SystemExit(f"falta {feat / 'pos_train.npy'} (e nao ha positivos alinhados)")
    neg = _carregar_vetor(feat / "neg_train.npy", permitir_privado=permitir_privado)
    acav = _carregar_vetor(dados / "raw" / "openwakeword" / ACAV_NOME,
                            permitir_privado=permitir_privado)
    val = _carregar_vetor(dados / "raw" / "openwakeword" / VAL_NOME,
                          permitir_privado=permitir_privado)
    game_hard = None
    hard_p = dados / "treino" / "game_hard.npy"
    if not permitir_privado:
        validar_fonte_publica(hard_p)
    if hard_p.exists():
        game_hard = np.load(hard_p, mmap_mode="r")
        log.info("negativos dificeis de jogo: %s", game_hard.shape)

    real_train = None
    real_treino_idx = np.zeros(0, dtype=np.int64)
    real_val_idx = np.zeros(0, dtype=np.int64)
    real_p = feat / "real_train.npy"
    split_p = feat / "real_split.json"
    if real_p.exists():
        if not permitir_privado:
            validar_fonte_publica(real_p); validar_fonte_publica(split_p)
        if not split_p.exists():
            raise SystemExit(f"falta {split_p} para separar real_train por video")
        real_train = _carregar_vetor(real_p, permitir_privado=permitir_privado)
        split = json.loads(split_p.read_text(encoding="utf-8"))
        nomes = split.get("treino", [])
        videos = split.get("videos_treino", [])
        if len(nomes) != len(real_train) or not videos:
            raise SystemExit(f"real_split.json nao corresponde a {real_p}")
        real_treino_idx, real_val_idx = _split_real_por_video(nomes, videos, val_frac, seed)
        n_val_videos = max(1, int(round(len(videos) * val_frac)))
        log.info("real_train: %d clipes, treino=%d, val=%d, videos val=%d",
                 len(real_train), len(real_treino_idx), len(real_val_idx), n_val_videos)

    streams_treino = []
    for categoria in CATEGORIAS:
        meta_p = feat / f"stream_{categoria}_treino_meta.json"
        if not permitir_privado:
            validar_fonte_publica(meta_p)
        if not meta_p.exists():
            raise SystemExit(f"falta {meta_p} (rode features.py --streaming)")
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        feats_p = dados / meta["arquivo_features"]
        feats = _carregar_vetor(feats_p, permitir_privado=permitir_privado)
        wav_dir = dados / "raw" / categoria / "wav"
        raw_dir = dados / "raw" / categoria
        if not permitir_privado:
            pasta_audio = wav_dir if not meta.get("arquivos") or (wav_dir / meta["arquivos"][0]).exists() else raw_dir
            validar_fonte_publica(pasta_audio)
            for nome in meta.get("arquivos", []):
                validar_fonte_publica(pasta_audio / nome)
        segmentos = M.segmentos_do_meta(meta, dados, categoria)
        streams_treino.append(AmostradorStream(feats, segmentos, categoria))
        log.info("stream treino %s: %d chunks, %d arquivos", categoria, len(feats), len(segmentos))

    if pos is not None:
        n_val = max(1, int(round(len(pos) * val_frac)))
        ordem = np.random.default_rng(seed).permutation(len(pos))
        pos_val = np.sort(ordem[:n_val])
        pos_treino = np.sort(ordem[n_val:])
    else:
        pos_treino = np.zeros(0, dtype=np.int64)
        pos_val = np.zeros(0, dtype=np.int64)
    return {
        "pos": pos,
        "alinhado": alinhado,
        "neg": neg,
        "acav": acav,
        "val": val,
        "streams": streams_treino,
        "game_hard": game_hard,
        "real_train": real_train,
        "real_treino_idx": real_treino_idx,
        "real_val_idx": real_val_idx,
        "pos_treino": pos_treino,
        "pos_val": pos_val,
    }


# --------------------------------------------------------------------------- #
# rede
# --------------------------------------------------------------------------- #
def _lr_cosine(passo: int, total: int, base: float, aquecimento: int = 100) -> float:
    """Warmup curto + cosine ate 5% do LR (como o openWakeWord)."""
    if passo < aquecimento:
        return base * (0.05 + 0.95 * passo / max(1, aquecimento))
    prog = min(1.0, (passo - aquecimento) / max(1, total - aquecimento))
    return base * (0.05 + 0.95 * 0.5 * (1.0 + math.cos(math.pi * prog)))


def criar_rede(camada: int, blocos: int):
    import torch
    import torch.nn as nn

    class Bloco(nn.Module):
        def __init__(self):
            super().__init__()
            self.linear = nn.Linear(camada, camada)
            self.norm = nn.LayerNorm(camada)
            self.relu = nn.ReLU()

        def forward(self, x):
            return self.relu(self.norm(self.linear(x)))

    class Rede(nn.Module):
        def __init__(self):
            super().__init__()
            self.flatten = nn.Flatten()
            self.entrada = nn.Linear(M.JANELA * M.DIM, camada)
            self.norm = nn.LayerNorm(camada)
            self.relu = nn.ReLU()
            self.blocos = nn.ModuleList([Bloco() for _ in range(blocos)])
            self.saida = nn.Linear(camada, 1)
            self.sigmoid = nn.Sigmoid()

        def forward(self, x):
            x = self.relu(self.norm(self.entrada(self.flatten(x))))
            for bloco in self.blocos:
                x = bloco(x)
            return self.sigmoid(self.saida(x))

    return Rede()


# --------------------------------------------------------------------------- #
# lote de treino
# --------------------------------------------------------------------------- #
def _linhas_mmap(arr, indices: np.ndarray) -> np.ndarray:
    """Le linhas de um mmap em ordem (menos seeks) e devolve float32 na ordem pedida."""
    ordem = np.argsort(indices)
    linhas = np.asarray(arr[indices[ordem]], dtype=np.float32)
    saida = np.empty_like(linhas)
    saida[ordem] = linhas
    return saida


def montar_lote(d: dict, args, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    partes_x, partes_y = [], []
    n_real = (int(round(args.lote_pos * args.frac_real_positivo))
              if len(d.get("real_treino_idx", [])) else 0)
    if args.frac_real_positivo > 0 and d.get("real_train") is None:
        raise SystemExit("--frac-real-positivo exige features/real_train.npy e real_split.json")
    if n_real:
        idx_real = rng.choice(d["real_treino_idx"], size=n_real, replace=True)
        partes_x.append(_linhas_mmap(d["real_train"], idx_real))
        partes_y.append(np.ones(n_real, np.float32))
    n_positivo = args.lote_pos - n_real
    if d["alinhado"] is not None:
        n_antigo = int(round(n_positivo * args.pos_antigo_frac)) if d["pos"] is not None else 0
        n_alinhado = n_positivo - n_antigo
        if n_alinhado > 0:
            x_pos, y_pos = d["alinhado"].amostrar(
                n_alinhado, rng, args.frac_janela_negativa, 0.0)
            partes_x.append(x_pos); partes_y.append(y_pos)
        if n_antigo > 0:
            idx = rng.choice(d["pos_treino"], size=n_antigo, replace=True)
            partes_x.append(_linhas_mmap(d["pos"], idx))
            partes_y.append(np.ones(n_antigo, np.float32))
    else:
        pos_idx = rng.choice(d["pos_treino"], size=n_positivo, replace=True)
        if n_positivo:
            partes_x.append(_linhas_mmap(d["pos"], pos_idx))
            partes_y.append(np.ones(n_positivo, np.float32))
    neg_idx = rng.choice(len(d["neg"]), size=args.lote_neg, replace=True)
    acav_idx = rng.integers(0, len(d["acav"]), size=args.lote_acav)
    partes_x.append(_linhas_mmap(d["neg"], neg_idx))
    partes_x.append(_linhas_mmap(d["acav"], acav_idx))
    partes_y.append(np.zeros(args.lote_neg, np.float32))
    partes_y.append(np.zeros(args.lote_acav, np.float32))
    if d.get("game_hard") is not None and args.lote_game_hard > 0:
        hard_idx = rng.integers(0, len(d["game_hard"]), size=args.lote_game_hard)
        partes_x.append(_linhas_mmap(d["game_hard"], hard_idx))
        partes_y.append(np.zeros(args.lote_game_hard, np.float32))
    por_stream = max(1, args.lote_stream // max(1, len(d["streams"])))
    for amostrador in d["streams"]:
        partes_x.append(amostrador.amostrar(por_stream, rng))
        partes_y.append(np.zeros(por_stream, np.float32))
    x = np.concatenate(partes_x, axis=0)
    y = np.concatenate(partes_y).astype(np.float32)
    return x, y


# --------------------------------------------------------------------------- #
# metricas de validacao
# --------------------------------------------------------------------------- #
def scores_janelas_torch(rede, feats, lote: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    """Pontua o stream inteiro de validacao (janela de 16, um passo por chunk)."""
    import torch

    n = len(feats) - M.JANELA + 1
    indices = np.arange(M.JANELA - 1, len(feats), dtype=np.int64)
    scores = np.empty(n, dtype=np.float32)
    rede.eval()
    with torch.no_grad():
        for a in range(0, n, lote):
            b = min(a + lote, n)
            idx = np.arange(a, b)[:, None] + np.arange(M.JANELA)[None, :]
            x = torch.from_numpy(np.asarray(feats[idx], dtype=np.float32))
            scores[a:b] = rede(x).numpy().reshape(-1)
    return indices, scores


def metricas_validacao(rede, d: dict, limiares: list[float]) -> dict:
    import torch

    rede.eval()
    ultima = None
    if d["alinhado"] is not None:
        pos_scores, ultima = d["alinhado"].scores_val(rede)
    else:
        pos_val = np.asarray(d["pos"][d["pos_val"]], dtype=np.float32)
        with torch.no_grad():
            pos_scores = rede(torch.from_numpy(pos_val)).numpy().reshape(-1)
    if d.get("real_train") is not None and len(d["real_val_idx"]):
        real_val = _linhas_mmap(d["real_train"], d["real_val_idx"])
        with torch.no_grad():
            real_scores = rede(torch.from_numpy(real_val)).numpy().reshape(-1)
        pos_scores = np.concatenate((pos_scores, real_scores))
    val_feats = d["val"]
    indices, scores = scores_janelas_torch(rede, val_feats)
    horas = len(indices) * M.PASSO_S / 3600.0
    saida = {
        "val_horas": round(horas, 3),
        "val_chunks": int(len(indices)),
        "pos_val": int(len(pos_scores)),
        "recall": {},
        "recall_ultima_janela": {},
        "fa_h": {},
        "fa_limite95": {},
    }
    for limiar in limiares:
        disparos = M.contar_disparos(indices, scores, limiar)
        taxa, limite = M.fa_por_hora(len(disparos), horas)
        saida["recall"][limiar] = float(np.mean(pos_scores >= limiar))
        if ultima is not None:
            saida["recall_ultima_janela"][limiar] = float(np.mean(ultima >= limiar))
        saida["fa_h"][limiar] = float(taxa)
        saida["fa_limite95"][limiar] = float(limite)
    return saida


def chave_escolha(metricas: dict, limiar: float, fa_max: float) -> tuple:
    fa = metricas["fa_h"][limiar]
    recall = metricas["recall"][limiar]
    viavel = recall > 0.0 and fa <= fa_max
    if viavel:
        return (1, recall, -fa)
    # fora da meta: equilibra recall e FA (1 disparo/h "custa" 0,01 de recall)
    return (0, recall - 0.01 * fa, recall)


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def exportar(rede, caminho: Path) -> None:
    import torch

    caminho.parent.mkdir(parents=True, exist_ok=True)
    rede = rede.cpu().eval()
    exemplo = torch.zeros(1, M.JANELA, M.DIM, dtype=torch.float32)
    comum = dict(
        input_names=["input"],
        output_names=["output"],
        opset_version=17,
        do_constant_folding=True,
    )
    try:
        torch.onnx.export(rede, exemplo, str(caminho), dynamo=False, **comum)
    except TypeError:  # torch antigo nao conhece dynamo=
        torch.onnx.export(rede, exemplo, str(caminho), **comum)
    log.info("exportado %s (%.1f KB)", caminho, caminho.stat().st_size / 1024)


def verificar_modelo(caminho: Path) -> dict:
    """Confere forma do ONNX e o caminho real de producao (ronaldo.detector)."""
    sessao = M.sessao_onnx(caminho)
    entrada = sessao.get_inputs()[0]
    saida = sessao.get_outputs()[0]
    forma_in = [int(x) if isinstance(x, int) else x for x in entrada.shape]
    forma_out = [int(x) if isinstance(x, int) else x for x in saida.shape]
    if forma_in != [1, M.JANELA, M.DIM]:
        raise SystemExit(f"entrada {forma_in} != [1, {M.JANELA}, {M.DIM}]")
    if forma_out != [1, 1]:
        raise SystemExit(f"saida {forma_out} != [1, 1]")

    from ronaldo.detector import WakeWord

    modelo = WakeWord(caminho, REPO / "models")
    rng = np.random.default_rng(0)
    audio = (rng.normal(0, 0.02, M.SR * 2) * 32768).astype(np.int16)
    notas = []
    for i in range(0, len(audio) - M.CHUNK + 1, M.CHUNK):
        nota = modelo.scores(audio[i : i + M.CHUNK])[caminho.stem]
        notas.append(nota)
    if not all(np.isfinite(notas)) or min(notas) < 0.0 or max(notas) > 1.0:
        raise SystemExit(f"WakeWord devolveu notas fora de 0..1: {notas}")
    return {
        "entrada": forma_in,
        "saida": forma_out,
        "bytes": caminho.stat().st_size,
        "wakeword_notas": [round(float(n), 4) for n in notas[-3:]],
    }


def _caminho_fora_de_git(caminho: str | Path, nome: str) -> Path:
    """Valida caminhos pessoais sem permitir escrita dentro de qualquer worktree."""
    real = Path(os.path.realpath(Path(caminho).expanduser()))
    if ".git" in real.parts:
        raise SystemExit(f"{nome} deve ficar fora de caminhos .git: {real}")
    if any(parte == "models" for parte in real.parts):
        raise SystemExit(f"{nome} deve ficar fora de qualquer pasta models/: {real}")

    ancestral = real
    if ancestral.is_file():
        ancestral = ancestral.parent
    while not ancestral.exists() and ancestral != ancestral.parent:
        ancestral = ancestral.parent
    try:
        resultado = subprocess.run(
            ["git", "-C", str(ancestral), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
    except OSError as erro:
        raise SystemExit(f"nao foi possivel validar {nome} com Git: {erro}") from erro
    if resultado.returncode != 0:
        if "not a git repository" in resultado.stderr.lower():
            return real
        raise SystemExit(f"nao foi possivel validar {nome} com Git: {resultado.stderr.strip()}")
    raiz = resultado.stdout.strip()
    if not raiz:
        raise SystemExit(f"nao foi possivel validar {nome}: Git nao informou a raiz")
    raiz_real = Path(os.path.realpath(raiz))
    try:
        real.relative_to(raiz_real)
    except ValueError:
        return real
    raise SystemExit(f"{nome} deve ficar fora de qualquer worktree Git: {real}")


def validar_caminhos_pessoais(saida: str | Path | None, dados: str | Path | None) -> None:
    if saida is None:
        raise SystemExit("--pessoal exige --saida explícito")
    _caminho_fora_de_git(saida, "--saida")
    if dados is not None:
        _caminho_fora_de_git(dados, "--pessoal-dados")


def gravar_modelo(rede, caminho: Path, pessoal: bool = False,
                 pessoal_dados: str | Path | None = None) -> None:
    """Revalida o destino pessoal imediatamente antes de gravar o ONNX."""
    if pessoal:
        validar_caminhos_pessoais(caminho, pessoal_dados)
    exportar(rede, caminho)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dados", default=str(Path.home() / "data" / "gol"))
    ap.add_argument("--saida")
    ap.add_argument("--pessoal", action="store_true", help="exige saída e dados pessoais fora de worktrees Git")
    ap.add_argument("--pessoal-dados", help="pasta de áudio pessoal; deve ficar fora de worktrees Git e models/")
    ap.add_argument("--variacao", default="a")
    ap.add_argument("--epocas", type=int, default=24)
    ap.add_argument("--passos-por-epoca", type=int, default=0, help="0 = len(pos_treino)//lote_pos")
    ap.add_argument("--lote-pos", type=int, default=64)
    ap.add_argument("--frac-janela-negativa", type=float, default=0.25,
                    help="fracao do lote de positivos alinhados que vira janela antes da palavra")
    ap.add_argument("--pos-antigo-frac", type=float, default=0.0,
                    help="fracao do lote de positivos vinda do pos_train.npy antigo (janela final)")
    ap.add_argument("--frac-real-positivo", type=float, default=0.0,
                    help="fracao dos positivos alinhados vinda do real_train (gritos humanos)")
    ap.add_argument("--lote-game-hard", type=int, default=128,
                    help="negativos dificeis minerados do stream de treino de jogo")
    ap.add_argument("--lote-neg", type=int, default=64)
    ap.add_argument("--lote-acav", type=int, default=512)
    ap.add_argument("--lote-stream", type=int, default=256)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--agenda-lr", choices=["cosine", "fixo"], default="cosine")
    ap.add_argument("--mineracao", dest="mineracao", action="store_true", default=True,
                    help="so negativos dificeis e positivos nao aprendidos (openWakeWord)")
    ap.add_argument("--sem-mineracao", dest="mineracao", action="store_false")
    ap.add_argument("--peso-negativo-max", type=float, default=200.0)
    ap.add_argument("--camada", type=int, default=32)
    ap.add_argument("--blocos", type=int, default=1)
    ap.add_argument("--val-frac", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--paciencia", type=int, default=6)
    ap.add_argument("--fa-max-checkpoint", type=float, default=2.0,
                    help="FA/h (sem portao) maxima para o checkpoint; o portao so reduz")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--smoke", action="store_true", help="nao exige MANIFESTO.json")
    args = ap.parse_args()

    if args.pessoal:
        validar_caminhos_pessoais(args.saida, args.pessoal_dados)
    elif args.saida is None:
        args.saida = str(REPO / "models" / "gol_grito.onnx")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dados = Path(args.dados).expanduser()
    if not args.pessoal:
        validar_fontes_publicas(dados)
    if not args.smoke and not (dados / "MANIFESTO.json").exists():
        raise SystemExit(f"aguarde {dados / 'MANIFESTO.json'} (o outro soldado escreve no fim)")

    import torch

    torch.set_num_threads(max(1, args.threads))
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    rng = np.random.default_rng(args.seed)

    d = carregar_dados(dados, args.val_frac, args.seed, permitir_privado=args.pessoal)
    n_treino = (len(d["alinhado"].treino_idx) if d["alinhado"] is not None
                else len(d["pos_treino"]))
    n_val = len(d["alinhado"].val_idx) if d["alinhado"] is not None else len(d["pos_val"])
    log.info(
        "dados: pos_treino=%d pos_val=%d neg=%d acav=%d val_chunks=%d game_hard=%s",
        n_treino, n_val, len(d["neg"]), len(d["acav"]), len(d["val"]),
        None if d.get("game_hard") is None else len(d["game_hard"]),
    )
    passos = args.passos_por_epoca or max(1, n_treino // args.lote_pos)
    total_passos = args.epocas * passos

    rede = criar_rede(args.camada, args.blocos)
    n_params = sum(p.numel() for p in rede.parameters())
    log.info("rede: %d parametros (camada=%d, blocos=%d)", n_params, args.camada, args.blocos)
    otimizador = torch.optim.Adam(rede.parameters(), lr=args.lr)
    perda_fn = torch.nn.functional.binary_cross_entropy

    melhor = None
    melhor_chave = None
    melhor_epoca = None
    historico = []
    saida_dir = dados / "treino"
    saida_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sem_melhora = 0

    for epoca in range(1, args.epocas + 1):
        rede.train()
        soma = 0.0
        for passo in range(passos):
            passo_global = (epoca - 1) * passos + passo
            fracao = passo_global / max(1, total_passos - 1)
            peso_neg = 1.0 + (args.peso_negativo_max - 1.0) * fracao
            if args.agenda_lr == "cosine":
                for grupo in otimizador.param_groups:
                    grupo["lr"] = _lr_cosine(passo_global, total_passos, args.lr)
            x, y = montar_lote(d, args, rng)
            w = np.where(y == 1, 1.0, peso_neg).astype(np.float32)
            xt = torch.from_numpy(x)
            yt = torch.from_numpy(y)
            wt = torch.from_numpy(w)
            otimizador.zero_grad(set_to_none=True)
            pred = rede(xt).reshape(-1)
            if args.mineracao:
                # openWakeWord: so negativos dificeis e positivos ainda nao aprendidos
                with torch.no_grad():
                    mascara = ((yt == 0) & (pred >= 0.001)) | ((yt == 1) & (pred < 0.999))
                if int(mascara.sum()) >= 32:
                    pred = pred[mascara]
                    yt = yt[mascara]
                    wt = wt[mascara]
            perda = perda_fn(torch.clamp(pred, 1e-6, 1 - 1e-6), yt, weight=wt)
            perda.backward()
            torch.nn.utils.clip_grad_norm_(rede.parameters(), 5.0)
            otimizador.step()
            soma += float(perda.detach())
        metrica = metricas_validacao(rede, d, LIMIARES)
        metrica["epoca"] = epoca
        metrica["perda"] = soma / passos
        metrica["peso_negativo"] = peso_neg
        historico.append(metrica)
        chave = chave_escolha(metrica, 0.5, args.fa_max_checkpoint)
        log.info(
            "epoca %d/%d perda=%.4f recall@0.5=%.3f ultima=%.3f FA/h@0.5=%.3f (lim95 %.3f) peso_neg=%.0f [%.0fs]",
            epoca, args.epocas, metrica["perda"], metrica["recall"][0.5],
            metrica.get("recall_ultima_janela", {}).get(0.5, float("nan")),
            metrica["fa_h"][0.5], metrica["fa_limite95"][0.5], peso_neg, time.time() - t0,
        )
        if melhor_chave is None or chave > melhor_chave:
            melhor_chave = chave
            melhor_epoca = epoca
            melhor = {k: v.detach().cpu().clone() for k, v in rede.state_dict().items()}
            sem_melhora = 0
        else:
            sem_melhora += 1
        if args.smoke and epoca >= args.epocas:
            break
        if sem_melhora >= args.paciencia:
            log.info("early stop: %d epocas sem melhora", sem_melhora)
            break

    if melhor is not None:
        rede.load_state_dict(melhor)
        log.info("checkpoint escolhido: epoca %s (chave %s)", melhor_epoca, melhor_chave)
    caminho = Path(args.saida)
    gravar_modelo(rede, caminho, args.pessoal, args.pessoal_dados)
    verificacao = verificar_modelo(caminho)
    log.info("verificacao: %s", json.dumps(verificacao, ensure_ascii=False))

    resumo = {
        "variacao": args.variacao,
        "args": vars(args),
        "parametros": n_params,
        "passos_por_epoca": passos,
        "epocas_rodadas": len(historico),
        "historico": historico,
        "melhor_chave": list(melhor_chave) if melhor_chave else None,
        "melhor_epoca": melhor_epoca,
        "verificacao": verificacao,
        "segundos": round(time.time() - t0, 1),
    }
    destino = saida_dir / f"metricas_{args.variacao}.json"
    destino.write_text(json.dumps(resumo, indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("metricas em %s", destino)


if __name__ == "__main__":
    main()
