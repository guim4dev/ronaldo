#!/usr/bin/env python3
"""Gera os negativos sinteticos do modelo gol_grito (~20 mil clipes).

Conteudo (vozes de TREINO: Piper faber, edresson, cadu):
- fala NORMAL com "gol" no meio (>= 300 frases: "o gol foi bonito", "que gol",
  "foi gol do Flamengo", ...) e com palavras parecidas (sol, gola, goleiro,
  golfe, alcool, Google, gado, vou, nao, vai);
- frases neutras de conversa;
- palavras curtas GRITADAS que NAO sao gol ("vai!", "nao!", "isso!", "boa!",
  "chuta!", "uh!"), com o MESMO aumento de grito dos positivos.

Nada de aumento de grito nas frases: elas sao fala normal, no volume normal.
Saida: $GOL_DATA/work/neg_train/*.wav (16 kHz mono). Nada vai para o git.

Uso:
  uv run python gerar_negativos.py --n-fala 17000 --n-grito 3000 --workers 8
"""

from __future__ import annotations

import argparse
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

import comum as C

BASE = C.WORK / "tts_negativos"
LENGTH_SCALES = (0.95, 1.15)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def frases() -> list[str]:
    return C.frases_com_gol() + C.FRASES_PARECIDAS + C.FRASES_NEUTRAS


def _sintetizar_base(args: tuple[str, str, float, Path]) -> str | None:
    frase, voz, ls, alvo = args
    if alvo.exists() and alvo.stat().st_size > 2000:
        return str(alvo)
    try:
        x = C.piper_texto(frase, voz, ls, 0.667, 0.8)
    except RuntimeError as exc:
        log(f"piper falhou {voz}: {exc}")
        return None
    C.salvar_wav16(alvo, x)
    return str(alvo)


def gerar_bases(workers: int, max_frases: int | None = None) -> list[dict]:
    tarefas = []
    lista = frases()[:max_frases] if max_frases else frases()
    for fi, frase in enumerate(lista):
        for voz in C.VOZES_TREINO:
            for li, ls in enumerate(LENGTH_SCALES):
                alvo = BASE / f"f{fi:03d}_{voz}_l{li}.wav"
                tarefas.append((frase, voz, ls, alvo))
    log(f"bases de fala normal: {len(tarefas)} sinteses")
    bases: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(_sintetizar_base, t): t for t in tarefas}
        for f in as_completed(futuros):
            frase, voz, ls, alvo = futuros[f]
            caminho = f.result()
            if caminho:
                bases.append({"frase": frase, "voz": voz, "ls": ls, "arquivo": caminho})
    log(f"bases prontas: {len(bases)}")
    return bases


def _sintetizar_grito(args: tuple[str, str, Path]) -> str | None:
    palavra, voz, alvo = args
    if alvo.exists() and alvo.stat().st_size > 2000:
        return str(alvo)
    try:
        x = C.piper_texto(palavra, voz, 0.7, 0.8, 0.7)
    except RuntimeError:
        return None
    C.salvar_wav16(alvo, x)
    return str(alvo)


def bases_gritadas(workers: int) -> list[dict]:
    tarefas = [(p, v, BASE / f"grito_{p.strip('!')}_{v}.wav") for p in C.PALAVRAS_GRITADAS for v in C.VOZES_TREINO]
    bases = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for (palavra, voz, alvo), caminho in zip(tarefas, pool.map(_sintetizar_grito, tarefas)):
            if caminho:
                bases.append({"frase": palavra, "voz": voz, "arquivo": caminho, "grito": True})
    log(f"bases gritadas: {len(bases)}")
    return bases


def montar_fala(i: int, bases: list[dict]) -> dict:
    rng = C.semente("neg:fala", i)
    base = bases[rng.randrange(len(bases))]
    x, sr = C.ler_audio(base["arquivo"])
    x = C.resample(x, sr)
    receita = {"tipo": "fala_normal", "frase": base["frase"], "voz": base["voz"],
               "rir": False, "snr_db": None, "ganho_db": 0.0}
    # fala normal: so ganho pequeno (o volume vira ruido de calibracao depois)
    g = rng.uniform(-6.0, 4.0)
    y = C.ganho(x, g)
    receita["ganho_db"] = round(g, 2)
    y = C.normalizar(y, 0.9)
    if rng.random() < 0.30:
        y = C.aplicar_rir(y, rng, rng.uniform(0.15, 0.40))
        receita["rir"] = True
    if rng.random() < 0.50:
        fundo = C.fundo_aleatorio(rng, [("noise", 0.4), ("game", 0.3), ("music", 0.3)], 3.0)
        snr = rng.uniform(10.0, 25.0)
        y = C.misturar_snr(y, fundo, snr, rng)
        receita["snr_db"] = round(snr, 2)
    if rng.random() < 0.35:
        fundo = C.fundo_aleatorio(rng, [("game", 0.5), ("noise", 0.3), ("music", 0.2)], 3.0)
    else:
        fundo = None
    janela = C.janela_com_fundo(y, fundo, rng)
    destino = C.WORK / "neg_train" / f"fala_{i:06d}.wav"
    C.salvar_wav16(destino, janela)
    return {"i": i, "arquivo": str(destino), "receita": receita}


def montar_grito(i: int, bases: list[dict]) -> dict:
    rng = C.semente("neg:grito", i)
    base = bases[rng.randrange(len(bases))]
    x, sr = C.ler_audio(base["arquivo"])
    x = C.resample(x, sr)
    semitons = rng.uniform(1.0, 6.0)
    fator = rng.uniform(1.0, 3.0)
    forca = rng.uniform(1.5, 6.0)
    y = C.mudar_pitch(x, semitons)
    y = C.esticar_vogal(y, fator)
    y = C.comprimir(y, forca)
    y = C.normalizar(C.ganho(y, rng.uniform(-3.0, 9.0)), 0.95)
    receita = {"tipo": "palavra_gritada", "frase": base["frase"], "voz": base["voz"],
               "semitons": round(semitons, 2), "vogal": round(fator, 2),
               "compressao": round(forca, 2), "rir": False, "snr_db": None}
    if rng.random() < 0.45:
        y = C.aplicar_rir(y, rng, rng.uniform(0.2, 0.5))
        receita["rir"] = True
    fundo = C.fundo_aleatorio(rng, [("game", 0.5), ("noise", 0.3), ("music", 0.2)], 3.0)
    snr = rng.uniform(0.0, 20.0)
    y = C.misturar_snr(y, fundo, snr, rng)
    receita["snr_db"] = round(snr, 2)
    janela = C.janela_com_fundo(y, fundo, rng)
    destino = C.WORK / "neg_train" / f"grito_{i:06d}.wav"
    C.salvar_wav16(destino, janela)
    return {"i": i, "arquivo": str(destino), "receita": receita}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-fala", type=int, default=17000)
    ap.add_argument("--n-grito", type=int, default=3000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-frases", type=int, default=None, help="limite so para teste rapido")
    args = ap.parse_args()
    destino = C.WORK / "neg_train"
    destino.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    n_frases = len(C.frases_com_gol())
    if n_frases < 300:
        raise SystemExit(f"so {n_frases} frases com gol (< 300 exigidas)")
    log(f"frases com gol: {n_frases}; parecidas: {len(C.FRASES_PARECIDAS)}; neutras: {len(C.FRASES_NEUTRAS)}")

    bases_fala = gerar_bases(args.workers, args.max_frases)
    bases_g = bases_gritadas(args.workers)
    if not bases_fala or not bases_g:
        raise SystemExit("faltam bases TTS")

    receitas: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futuros = [pool.submit(montar_fala, i, bases_fala) for i in range(args.n_fala)]
        futuros += [pool.submit(montar_grito, i, bases_g) for i in range(args.n_grito)]
        for n, f in enumerate(as_completed(futuros), 1):
            receitas.append(f.result())
            if n % 1000 == 0:
                log(f"{n}/{len(futuros)} ({n/(time.time()-t0):.1f} clipes/s)")
    receitas.sort(key=lambda r: (r["receita"]["tipo"], r["i"]))
    C.salvar_json(destino / "receitas.json", receitas)
    log(f"pronto: {len(receitas)} clipes em {destino} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
