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
        log.info(
            "alinhado: %d clipes (%d com janela positiva), val=%d, media pos=%.1f neg=%.1f",
            len(itens), len(usaveis), len(self.val_idx),
            float(np.mean([len(self.positivas[i]) for i in usaveis])),
            float(np.mean([len(self.negativas[i]) for i in self.com_neg])),
        )

    def _janela(self, i: int, k: int) -> np.ndarray:
        off = int(self.offsets[i])
        return np.asarray(self.stream[off + k - (M.JANELA - 1) : off + k + 1], dtype=np.float32)

    def amostrar(self, n: int, rng: np.random.Generator, frac_neg: float = 0.25):
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
                i = self.treino_idx[int(rng.integers(0, len(self.treino_idx)))]
                ks = self.positivas[i]
                k = ks[int(rng.integers(0, len(ks)))]
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
            pendentes.append(self._janela(i, int(self.chunks[i]) - 1))
            donos.append(j); tipos.append("ultima")
        drenar()
        return maximo, ultima


def _carregar_vetor(caminho: Path, mmap: bool = True) -> np.ndarray:
    if not caminho.exists():
        raise SystemExit(f"falta {caminho} (ver DADOS.md; espere o MANIFESTO.json)")
    return np.load(caminho, mmap_mode="r" if mmap else None)


def carregar_dados(dados: Path, val_frac: float, seed: int) -> dict:
    feat = dados / "features"
    alinhado = None
    pos = None
    stream_p = feat / "pos_v2_stream.npy"
    offsets_p = feat / "pos_v2_offsets.npy"
    meta_p = feat / "pos_v2_meta.json"
    if stream_p.exists() and offsets_p.exists() and meta_p.exists():
        alinhado = PositivosAlinhados(
            np.load(stream_p, mmap_mode="r"), np.load(offsets_p),
            json.loads(meta_p.read_text(encoding="utf-8")), val_frac, seed,
        )
    else:
        pos = _carregar_vetor(feat / "pos_train.npy")
    neg = _carregar_vetor(feat / "neg_train.npy")
    acav = _carregar_vetor(dados / "raw" / "openwakeword" / ACAV_NOME)
    val = _carregar_vetor(dados / "raw" / "openwakeword" / VAL_NOME)
    game_hard = None
    hard_p = dados / "treino" / "game_hard.npy"
    if hard_p.exists():
        game_hard = np.load(hard_p, mmap_mode="r")
        log.info("negativos dificeis de jogo: %s", game_hard.shape)

    streams_treino = []
    for categoria in CATEGORIAS:
        meta_p = feat / f"stream_{categoria}_treino_meta.json"
        if not meta_p.exists():
            raise SystemExit(f"falta {meta_p} (rode features.py --streaming)")
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        feats = _carregar_vetor(dados / meta["arquivo_features"])
        segmentos = M.segmentos_do_meta(meta, dados, categoria)
        streams_treino.append(AmostradorStream(feats, segmentos, categoria))
        log.info("stream treino %s: %d chunks, %d arquivos", categoria, len(feats), len(segmentos))

    if alinhado is not None:
        pos_treino = np.zeros(0, dtype=np.int64)
        pos_val = np.zeros(0, dtype=np.int64)
    else:
        n_val = max(1, int(round(len(pos) * val_frac)))
        ordem = np.random.default_rng(seed).permutation(len(pos))
        pos_val = np.sort(ordem[:n_val])
        pos_treino = np.sort(ordem[n_val:])
    return {
        "pos": pos,
        "alinhado": alinhado,
        "neg": neg,
        "acav": acav,
        "val": val,
        "streams": streams_treino,
        "game_hard": game_hard,
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
    if d["alinhado"] is not None:
        x_pos, y_pos = d["alinhado"].amostrar(args.lote_pos, rng, args.frac_janela_negativa)
        partes_x.append(x_pos); partes_y.append(y_pos)
    else:
        pos_idx = rng.choice(d["pos_treino"], size=args.lote_pos, replace=True)
        partes_x.append(_linhas_mmap(d["pos"], pos_idx))
        partes_y.append(np.ones(args.lote_pos, np.float32))
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


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dados", default=str(Path.home() / "data" / "gol"))
    ap.add_argument("--saida", default=str(REPO / "models" / "gol_grito.onnx"))
    ap.add_argument("--variacao", default="a")
    ap.add_argument("--epocas", type=int, default=24)
    ap.add_argument("--passos-por-epoca", type=int, default=0, help="0 = len(pos_treino)//lote_pos")
    ap.add_argument("--lote-pos", type=int, default=64)
    ap.add_argument("--frac-janela-negativa", type=float, default=0.25,
                    help="fracao do lote de positivos alinhados que vira janela antes da palavra")
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

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dados = Path(args.dados).expanduser()
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

    d = carregar_dados(dados, args.val_frac, args.seed)
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
    exportar(rede, caminho)
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
