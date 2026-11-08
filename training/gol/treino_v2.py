#!/usr/bin/env python3
"""Gera os positivos sinteticos ALINHADOS do `gol_grito` (iteracao 2).

Diferencas para o gerador da iteracao 1:

- mais vozes: Piper pt_BR (cadu, edresson, faber) + pt_PT (tugao). jeff fica
  reservado para o teste, como antes;
- aumento mais forte: pitch +1..+10 semitons, alongamento da vogal 1..4x,
  compressao ate 8, ganho -3..+12 dB, RIR e ruido a SNR 0..20 dB;
- o clipe tem fundo ANTES e DEPOIS da palavra, e o wav guarda o intervalo exato
  da palavra. Assim o treino pode montar as mesmas janelas de 16 embeddings que
  a producao ve (o fim da palavra em varios pontos da janela), em vez de so a
  ultima janela.

Saidas em $GOL_DATA:
  work/pos_train_v2/*.wav          clipes (fundo + palavra + fundo)
  work/pos_train_v2/receitas.json  intervalo da palavra em amostras
  features/pos_v2_stream.npy       embeddings por chunk, concatenados (float16)
  features/pos_v2_offsets.npy      inicio de cada clipe no array acima
  features/pos_v2_meta.json        metadados + intervalo da palavra em chunks

Uso:
  uv run python treino_v2.py --n 30000 --workers 8
  uv run python treino_v2.py --features --workers 8
"""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

import comum as C

BASE = C.WORK / "tts_pos_v2"
SAIDA = C.WORK / "pos_train_v2"
FEAT = C.FEATURES

VOZES = ["cadu", "edresson", "faber", "tugao"]
TEXTOS = [
    "gol!", "gool!", "gooool!", "goooooooool!", "golaço!", "golaaaaço!",
    "é gol!", "gol gol gol!", "golll!", "ééé gol!", "que golaço!", "gol do time!",
]
COMBOS = [
    (0.70, 0.55, 0.55), (0.85, 0.75, 0.70), (1.00, 0.60, 0.60),
    (1.20, 0.85, 0.80), (1.50, 0.70, 0.65), (1.90, 0.90, 0.80),
    (2.30, 0.80, 0.70), (2.60, 0.65, 0.60),
]
LEAD_S = 0.50
TRAIL_S = 0.65


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def piper_modelo(voz: str) -> tuple[Path, Path]:
    base = C.RAW / "piper" / "vozes" / voz
    modelos = sorted(base.rglob("*.onnx"))
    if not modelos:
        raise SystemExit(f"modelo piper de {voz} nao encontrado em {base}")
    return modelos[0], modelos[0].with_suffix(".onnx.json")


def piper_texto(texto: str, voz: str, ls: float, ns: float, nw: float) -> np.ndarray:
    import tempfile

    onnx, config = piper_modelo(voz)
    with tempfile.TemporaryDirectory(dir=str(C.ROOT / "work")) as td:
        cmd = [
            str(C.piper_bin()), "-m", str(onnx), "-c", str(config),
            "--length-scale", f"{ls:.2f}", "--noise-scale", f"{ns:.2f}",
            "--noise-w", f"{nw:.2f}", "--speaker", "0", "--output_dir", td,
        ]
        r = C.subprocess.run(cmd, input=texto + "\n", capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"piper falhou ({voz}): {r.stderr[-500:]}")
        saidas = sorted(Path(td).glob("*.wav"))
        if not saidas:
            raise RuntimeError(f"piper nao gerou wav para {texto!r}")
        x, sr = C.ler_audio(saidas[-1])
    return C.resample(x, sr)


def gerar_base(args: tuple[str, str, int, int, tuple[float, float, float]]) -> str | None:
    voz, texto, ti, ci, (ls, ns, nw) = args
    alvo = BASE / voz / f"{ti:02d}_c{ci:02d}.wav"
    if alvo.exists() and alvo.stat().st_size > 2000:
        return str(alvo)
    try:
        x = piper_texto(texto, voz, ls, ns, nw)
    except Exception as erro:  # noqa: BLE001
        log(f"base falhou {voz}/{texto}: {erro}")
        return None
    C.salvar_wav16(alvo, x)
    return str(alvo)


def preparar_bases(workers: int) -> list[dict]:
    BASE.mkdir(parents=True, exist_ok=True)
    tarefas = [(voz, texto, ti, ci, combo) for voz in VOZES
               for ti, texto in enumerate(TEXTOS) for ci, combo in enumerate(COMBOS)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        caminhos = list(pool.map(gerar_base, tarefas))
    bases = []
    for (voz, texto, ti, ci, _), caminho in zip(tarefas, caminhos):
        if caminho:
            bases.append({"voz": voz, "texto": texto, "ti": ti, "ci": ci, "arquivo": caminho})
    log(f"bases: {len(bases)}")
    return bases


def fundo(rng: random.Random, segundos: float) -> np.ndarray:
    escolhas = [("game", 0.45), ("noise", 0.25), ("music", 0.20), ("speech_ptbr", 0.10)]
    return C.fundo_aleatorio(rng, escolhas, segundos)


_CACHE: dict[str, list[np.ndarray]] = {}


def _cache_categoria(categoria: str, rng: random.Random) -> list[np.ndarray]:
    if categoria in _CACHE:
        return _CACHE[categoria]
    try:
        arquivos = C.pool(categoria)
    except SystemExit:
        _CACHE[categoria] = []
        return []
    rng.shuffle(arquivos)
    pedacos = []
    for arquivo in arquivos[:12]:
        try:
            x = C.trecho(arquivo, 12.0, rng)
        except Exception:  # noqa: BLE001
            continue
        if len(x) > 16000:
            pedacos.append(x)
    _CACHE[categoria] = pedacos
    return pedacos


def fundo_rapido(rng: random.Random, segundos: float) -> np.ndarray:
    """Fundo de um cache por processo: sem seek no disco a cada clipe."""
    categorias = ["game", "noise", "music", "speech_ptbr"]
    pesos = [0.45, 0.25, 0.20, 0.10]
    for _ in range(4):
        categoria = rng.choices(categorias, weights=pesos, k=1)[0]
        pedacos = _cache_categoria(categoria, rng)
        if not pedacos:
            continue
        x = pedacos[rng.randrange(len(pedacos))]
        n = int(segundos * C.SR)
        if len(x) < n:
            x = np.tile(x, int(np.ceil(n / len(x))))
        ini = rng.randrange(max(1, len(x) - n))
        return x[ini : ini + n].astype(np.float32)
    raise SystemExit("nenhum fundo disponivel")


def aumentar_forte(clip: np.ndarray, rng: random.Random) -> tuple[np.ndarray, dict]:
    semitons = rng.uniform(1.0, 10.0)
    fator = rng.uniform(1.0, 4.0)
    forca = rng.uniform(1.5, 8.0)
    g = rng.uniform(-3.0, 12.0)
    receita = {"semitons": round(semitons, 2), "vogal": round(fator, 2),
               "compressao": round(forca, 2), "ganho_db": round(g, 2),
               "rir": False, "snr_db": None, "fundo": None}
    y = C.mudar_pitch(clip, semitons)
    y = C.esticar_vogal(y, fator)
    y = C.comprimir(y, forca)
    y = C.ganho(y, g)
    y = C.normalizar(y, 0.95)
    if rng.random() < 0.45:
        y = C.aplicar_rir(y, rng, rng.uniform(0.20, 0.50))
        receita["rir"] = True
    return y, receita


def montar(i: int, bases: list[dict]) -> dict:
    rng = C.semente("posv2", i)
    base = bases[rng.randrange(len(bases))]
    x, sr = C.ler_audio(base["arquivo"])
    x = C.resample(x, sr)
    if len(x) < C.SR // 10:
        return {"i": i, "erro": "curto"}
    palavra, receita = aumentar_forte(x, rng)
    if len(palavra) > int(3.4 * C.SR):
        palavra = palavra[: int(3.4 * C.SR)]
    fundo_seg = LEAD_S + len(palavra) / C.SR + TRAIL_S + 0.2
    b = fundo_rapido(rng, fundo_seg)
    if len(b) < fundo_seg * C.SR:
        b = np.tile(b, int(np.ceil(fundo_seg * C.SR / max(len(b), 1))))
    lead = b[: int(LEAD_S * C.SR)]
    inicio = len(lead)
    resto = b[inicio + len(palavra): inicio + len(palavra) + int(TRAIL_S * C.SR)]
    audio = np.concatenate([lead, palavra, resto]).astype(np.float32)

    # ruido sobre o clipe inteiro (85% das vezes), SNR 0..20 dB
    if rng.random() < 0.85:
        ruido = fundo_rapido(rng, len(audio) / C.SR + 0.2)
        snr = rng.uniform(0.0, 20.0)
        audio = C.misturar_snr(audio, ruido, snr, rng)
        receita["snr_db"] = round(snr, 2)
        receita["fundo"] = "misto"
    # o SNR pode mudar o comprimento? nao. Normaliza sem deslocar a palavra.
    pico = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if pico > 1e-9:
        audio = (audio / pico * 0.95).astype(np.float32)

    destino = SAIDA / f"{i:06d}.wav"
    C.salvar_wav16(destino, audio)
    return {
        "i": i, "arquivo": str(destino), "base": base["arquivo"], "voz": base["voz"],
        "origem": "piper", "texto": base["texto"], "receita": receita,
        "inicio": int(inicio), "fim": int(inicio + len(palavra)),
        "total": int(len(audio)),
    }


def gerar(args) -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    bases = preparar_bases(args.workers)
    if not bases:
        raise SystemExit("nenhuma base TTS")
    log(f"positivos v2: alvo {args.n}, {args.workers} workers")
    feitos = erros = 0
    receitas = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futuros = [pool.submit(montar, i, bases) for i in range(args.n)]
        for f in as_completed(futuros):
            r = f.result()
            feitos += 1
            if "erro" in r:
                erros += 1
            else:
                receitas.append(r)
            if feitos % 1000 == 0:
                dt = time.time() - t0
                log(f"{feitos}/{args.n} ({feitos/dt:.1f} clipes/s) erros={erros}")
    receitas.sort(key=lambda r: r["i"])
    C.salvar_json(SAIDA / "receitas.json", receitas)
    log(f"pronto: {len(receitas)} clipes, {erros} erros, {time.time()-t0:.0f}s")


# --------------------------------------------------------------------------- #
# features streaming por clipe + offsets
# --------------------------------------------------------------------------- #
def _stream_worker(caminhos: list[str]):
    import features as F

    partes = []
    for caminho in caminhos:
        f, _ = F.features_streaming(Path(caminho))
        partes.append(f.astype(np.float16))
    return partes


def extrair_features(workers: int) -> None:
    import features as F

    receitas = json.loads((SAIDA / "receitas.json").read_text(encoding="utf-8"))
    caminhos = [r["arquivo"] for r in receitas]
    partes = [caminhos[i::workers] for i in range(workers)]
    resultados: dict[int, list[np.ndarray]] = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(_stream_worker, p): i for i, p in enumerate(partes) if p}
        for n, f in enumerate(as_completed(futuros), 1):
            resultados[futuros[f]] = f.result()
            log(f"  features: lote {n}/{len(futuros)} ({time.time()-t0:.0f}s)")
    blocos = []
    meta = []
    offsets = [0]
    for i, r in enumerate(receitas):
        lote = resultados[i % workers].pop(0)
        blocos.append(lote)
        n = len(lote)
        offsets.append(offsets[-1] + n)
        meta.append({
            "i": r["i"], "arquivo": Path(r["arquivo"]).name, "voz": r["voz"],
            "texto": r["texto"], "total": r["total"],
            "inicio_chunk": r["inicio"] / 1280.0, "fim_chunk": r["fim"] / 1280.0,
            "chunks": int(n),
        })
    stream = np.concatenate(blocos) if blocos else np.zeros((0, 96), np.float16)
    FEAT.mkdir(parents=True, exist_ok=True)
    np.save(FEAT / "pos_v2_stream.npy", stream)
    np.save(FEAT / "pos_v2_offsets.npy", np.asarray(offsets, dtype=np.int64))
    (FEAT / "pos_v2_meta.json").write_text(
        json.dumps({"clipes": len(meta), "chunks": int(len(stream)), "itens": meta},
                   ensure_ascii=False), encoding="utf-8")
    log(f"features: {stream.shape} ({len(meta)} clipes) em {FEAT}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=30000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--features", action="store_true", help="so extrai as features dos wavs ja gerados")
    args = ap.parse_args()
    if args.features:
        extrair_features(args.workers)
    else:
        gerar(args)


if __name__ == "__main__":
    main()
