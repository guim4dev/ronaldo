#!/usr/bin/env python3
"""Gera os gritos sinteticos (positivos) do modelo gol_grito.

TREINO (vozes que o modelo ve): Piper faber, edresson, cadu.
TESTE (vozes reservadas): Piper jeff + edge-tts pt-BR (Francisca, Antonio,
Thalita) e pt-PT (Raquel, Duarte).

Aumento "grito" no treino: pitch +1..+6 semitons, time-stretch da vogal 1..3x,
compressao/clipping leve, ganho, RIR e mistura com ruido/torcida/jogo/musica a
SNR 0..20 dB. Saida: wav 16 kHz mono em $GOL_DATA/work/pos_train e pos_test.
Nenhum audio vai para o git.

Uso:
  uv run python gerar_positivos.py --split treino --n 20000 --workers 8
  uv run python gerar_positivos.py --split teste  --n 1000
"""

from __future__ import annotations

import argparse
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

import comum as C

BASE = C.WORK / "tts_positivos"

COMBOS_TREINO = [
    # (length_scale, noise_scale, noise_w)
    (0.80, 0.55, 0.55),
    (0.95, 0.66, 0.60),
    (1.10, 0.75, 0.70),
    (1.35, 0.85, 0.75),
    (1.65, 0.70, 0.65),
    (2.00, 0.90, 0.80),
    (2.50, 0.80, 0.70),
    (1.20, 0.60, 0.55),
]

COMBOS_TESTE = [
    (0.85, 0.55, 0.55),
    (1.05, 0.65, 0.60),
    (1.40, 0.80, 0.70),
    (1.90, 0.75, 0.65),
    (2.30, 0.85, 0.75),
    (1.20, 0.60, 0.60),
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# bases TTS (uma vez por combinacao voz x texto x parametros)
# --------------------------------------------------------------------------- #
def gerar_bases_piper(vozes: list[str], combos: list[tuple[float, float, float]],
                      subdir: str) -> list[dict]:
    bases: list[dict] = []
    for voz in vozes:
        C.piper_modelo(voz)  # falha cedo se a voz nao foi baixada
        for ti, texto in enumerate(C.TEXTOS_POSITIVOS):
            for ci, (ls, ns, nw) in enumerate(combos):
                alvo = BASE / subdir / f"{voz}_{ti:02d}" / f"c{ci:02d}.wav"
                if not alvo.exists() or alvo.stat().st_size < 2000:
                    try:
                        x = C.piper_texto(texto, voz, ls, ns, nw)
                    except RuntimeError as exc:
                        log(f"piper falhou {voz} {texto!r}: {exc}")
                        continue
                    C.salvar_wav16(alvo, x)
                bases.append({"voz": voz, "origem": "piper", "texto": texto, "ti": ti, "ci": ci,
                              "arquivo": str(alvo)})
    return bases


def gerar_bases_treino() -> list[dict]:
    bases = gerar_bases_piper(C.VOZES_TREINO, COMBOS_TREINO, "treino")
    log(f"bases de treino: {len(bases)}")
    return bases


def gerar_bases_teste() -> list[dict]:
    bases = gerar_bases_piper(C.VOZES_TESTE, COMBOS_TESTE, "teste")
    # edge-tts: vozes reservadas, com rate variado (mais agudo/rapido = grito)
    for voz in C.EDGE_TESTE:
        for ti, texto in enumerate(C.TEXTOS_POSITIVOS):
            for vi, rate in enumerate(("+0%", "+15%", "+30%", "+45%")):
                alvo = BASE / "teste" / "edge" / f"{voz}_{ti:02d}_{vi:02d}.wav"
                if not alvo.exists() or alvo.stat().st_size < 2000:
                    try:
                        x = C.edge_frase(texto, voz, rate=rate)
                    except (RuntimeError, TimeoutError) as exc:
                        log(f"edge falhou {voz} {texto}: {exc}")
                        continue
                    C.salvar_wav16(alvo, x)
                bases.append({"voz": voz, "origem": "edge", "texto": texto, "ti": ti, "ci": vi,
                              "arquivo": str(alvo)})
    log(f"bases de teste: {len(bases)}")
    return bases


# --------------------------------------------------------------------------- #
# aumento
# --------------------------------------------------------------------------- #
def aumentar(clip: np.ndarray, rng: random.Random, com_rir: bool = True) -> tuple[np.ndarray, dict]:
    """Aplica o aumento de grito. Devolve (audio, receita)."""
    semitons = rng.uniform(1.0, 6.0)
    fator = rng.uniform(1.0, 3.0)
    forca = rng.uniform(1.5, 6.0)
    g = rng.uniform(-3.0, 9.0)
    receita = {"semitons": round(semitons, 2), "vogal": round(fator, 2),
               "compressao": round(forca, 2), "ganho_db": round(g, 2), "rir": False,
               "snr_db": None, "fundo": None}
    y = C.mudar_pitch(clip, semitons)
    y = C.esticar_vogal(y, fator)
    y = C.comprimir(y, forca)
    y = C.ganho(y, g)
    y = C.normalizar(y, 0.95)
    if com_rir and rng.random() < 0.45:
        y = C.aplicar_rir(y, rng, rng.uniform(0.20, 0.50))
        receita["rir"] = True
    return y, receita


def montar(i: int, split: str, bases: list[dict]) -> dict:
    rng = C.semente(f"pos:{split}", i)
    base = bases[rng.randrange(len(bases))]
    x, sr = C.ler_audio(base["arquivo"])
    x = C.resample(x, sr)
    if len(x) < C.SR // 10:
        return {"i": i, "erro": "curto"}
    clip, receita = aumentar(x, rng)

    if split == "teste":
        if i % 2 == 0:  # metade limpa (sem ruido de jogo)
            fundo, ruido = None, None
        else:
            arquivos = C.pool("game")
            arq = arquivos[rng.randrange(len(arquivos))]
            fundo = C.trecho(arq, 3.0, rng)
            ruido = fundo
    else:
        escolhas = [("game", 0.45), ("noise", 0.25), ("music", 0.20)]
        fundo = C.fundo_aleatorio(rng, escolhas, 3.0)
        ruido = fundo if rng.random() < 0.85 else None

    if ruido is not None:
        snr = rng.uniform(0.0, 20.0)
        clip = C.misturar_snr(clip, ruido, snr, rng)
        receita["snr_db"] = round(snr, 2)
        receita["fundo"] = "game" if split == "teste" else "misto"

    janela = C.janela_com_fundo(clip, fundo, rng)
    destino = C.WORK / f"pos_{'train' if split == 'treino' else 'test'}" / f"{i:06d}.wav"
    C.salvar_wav16(destino, janela)
    return {"i": i, "arquivo": str(destino), "base": base["arquivo"], "voz": base["voz"],
            "origem": base.get("origem", "piper"), "texto": base["texto"], "receita": receita}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["treino", "teste"], default="treino")
    ap.add_argument("--n", type=int, default=None, help="quantidade (padrao: 20000 treino, 1000 teste)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    n = args.n or (20000 if args.split == "treino" else 1000)
    sufixo = "train" if args.split == "treino" else "test"
    destino = C.WORK / f"pos_{sufixo}"
    destino.mkdir(parents=True, exist_ok=True)
    log(f"positivos {args.split}: alvo {n}, {args.workers} workers")

    bases = gerar_bases_treino() if args.split == "treino" else gerar_bases_teste()
    if not bases:
        raise SystemExit("nenhuma base TTS")

    feitos = 0
    erros = 0
    receitas: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futuros = [pool.submit(montar, i, args.split, bases) for i in range(n)]
        for f in as_completed(futuros):
            r = f.result()
            feitos += 1
            if "erro" in r:
                erros += 1
            else:
                receitas.append(r)
            if feitos % 1000 == 0:
                dt = time.time() - t0
                log(f"{feitos}/{n} ({feitos/dt:.1f} clipes/s) erros={erros}")
    receitas.sort(key=lambda r: r["i"])
    C.salvar_json(destino / "receitas.json", receitas)
    log(f"pronto: {feitos} clipes, {erros} erros, {time.time()-t0:.0f}s em {destino}")


if __name__ == "__main__":
    main()
