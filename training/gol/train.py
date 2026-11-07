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


def _carregar_vetor(caminho: Path, mmap: bool = True) -> np.ndarray:
    if not caminho.exists():
        raise SystemExit(f"falta {caminho} (ver DADOS.md; espere o MANIFESTO.json)")
    return np.load(caminho, mmap_mode="r" if mmap else None)


def carregar_dados(dados: Path, val_frac: float, seed: int) -> dict:
    feat = dados / "features"
    pos = _carregar_vetor(feat / "pos_train.npy")
    neg = _carregar_vetor(feat / "neg_train.npy")
    acav = _carregar_vetor(dados / "raw" / "openwakeword" / ACAV_NOME)
    val = _carregar_vetor(dados / "raw" / "openwakeword" / VAL_NOME)

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

    n_val = max(1, int(round(len(pos) * val_frac)))
    ordem = np.random.default_rng(seed).permutation(len(pos))
    val_idx = np.sort(ordem[:n_val])
    treino_idx = np.sort(ordem[n_val:])
    return {
        "pos": pos,
        "neg": neg,
        "acav": acav,
        "val": val,
        "streams": streams_treino,
        "pos_treino": treino_idx,
        "pos_val": val_idx,
    }


# --------------------------------------------------------------------------- #
# rede
# --------------------------------------------------------------------------- #
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


def montar_lote(d: dict, args, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pos_idx = rng.choice(d["pos_treino"], size=args.lote_pos, replace=True)
    neg_idx = rng.choice(len(d["neg"]), size=args.lote_neg, replace=True)
    acav_idx = rng.integers(0, len(d["acav"]), size=args.lote_acav)
    partes = [
        _linhas_mmap(d["pos"], pos_idx),
        _linhas_mmap(d["neg"], neg_idx),
        _linhas_mmap(d["acav"], acav_idx),
    ]
    por_stream = max(1, args.lote_stream // max(1, len(d["streams"])))
    for amostrador in d["streams"]:
        partes.append(amostrador.amostrar(por_stream, rng))
    x = np.concatenate(partes, axis=0)
    n_pos = args.lote_pos
    n_neg = len(x) - n_pos
    y = np.concatenate([np.ones(n_pos, np.float32), np.zeros(n_neg, np.float32)])
    w = np.ones(len(x), dtype=np.float32)
    return x, y, w


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

    pos_val = np.asarray(d["pos"][d["pos_val"]], dtype=np.float32)
    rede.eval()
    with torch.no_grad():
        pos_scores = rede(torch.from_numpy(pos_val)).numpy().reshape(-1)
    val_feats = d["val"]
    indices, scores = scores_janelas_torch(rede, val_feats)
    horas = len(indices) * M.PASSO_S / 3600.0
    saida = {
        "val_horas": round(horas, 3),
        "val_chunks": int(len(indices)),
        "pos_val": int(len(pos_val)),
        "recall": {},
        "fa_h": {},
        "fa_limite95": {},
    }
    for limiar in limiares:
        disparos = M.contar_disparos(indices, scores, limiar)
        taxa, limite = M.fa_por_hora(len(disparos), horas)
        saida["recall"][limiar] = float(np.mean(pos_scores >= limiar))
        saida["fa_h"][limiar] = float(taxa)
        saida["fa_limite95"][limiar] = float(limite)
    return saida


def chave_escolha(metricas: dict, limiar: float, fa_max: float) -> tuple:
    fa = metricas["fa_h"][limiar]
    recall = metricas["recall"][limiar]
    viavel = fa <= fa_max
    return (1 if viavel else 0, recall if viavel else -fa, recall, -fa)


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
    ap.add_argument("--epocas", type=int, default=18)
    ap.add_argument("--passos-por-epoca", type=int, default=0, help="0 = len(pos_treino)//lote_pos")
    ap.add_argument("--lote-pos", type=int, default=64)
    ap.add_argument("--lote-neg", type=int, default=64)
    ap.add_argument("--lote-acav", type=int, default=384)
    ap.add_argument("--lote-stream", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--peso-negativo-max", type=float, default=100.0)
    ap.add_argument("--camada", type=int, default=32)
    ap.add_argument("--blocos", type=int, default=1)
    ap.add_argument("--val-frac", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--paciencia", type=int, default=5)
    ap.add_argument("--fa-max-checkpoint", type=float, default=0.5)
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
    log.info(
        "dados: pos_treino=%d pos_val=%d neg=%d acav=%d val_chunks=%d",
        len(d["pos_treino"]), len(d["pos_val"]), len(d["neg"]), len(d["acav"]), len(d["val"]),
    )
    passos = args.passos_por_epoca or max(1, len(d["pos_treino"]) // args.lote_pos)
    total_passos = args.epocas * passos

    rede = criar_rede(args.camada, args.blocos)
    n_params = sum(p.numel() for p in rede.parameters())
    log.info("rede: %d parametros (camada=%d, blocos=%d)", n_params, args.camada, args.blocos)
    otimizador = torch.optim.Adam(rede.parameters(), lr=args.lr)
    perda_fn = torch.nn.functional.binary_cross_entropy

    melhor = None
    melhor_chave = None
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
            x, y, w = montar_lote(d, args, rng)
            w[args.lote_pos :] = peso_neg
            xt = torch.from_numpy(x)
            yt = torch.from_numpy(y)
            wt = torch.from_numpy(w)
            otimizador.zero_grad(set_to_none=True)
            pred = rede(xt).reshape(-1)
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
            "epoca %d/%d perda=%.4f recall@0.5=%.3f FA/h@0.5=%.3f (lim95 %.3f) peso_neg=%.0f [%.0fs]",
            epoca, args.epocas, metrica["perda"], metrica["recall"][0.5],
            metrica["fa_h"][0.5], metrica["fa_limite95"][0.5], peso_neg, time.time() - t0,
        )
        if melhor_chave is None or chave > melhor_chave:
            melhor_chave = chave
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
        "verificacao": verificacao,
        "segundos": round(time.time() - t0, 1),
    }
    destino = saida_dir / f"metricas_{args.variacao}.json"
    destino.write_text(json.dumps(resumo, indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("metricas em %s", destino)


if __name__ == "__main__":
    main()
