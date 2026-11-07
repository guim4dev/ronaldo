#!/usr/bin/env python3
"""Converte audio em features do openWakeWord, EXATAMENTE como ronaldo/detector.py.

Duas rotas, as mesmas do detector:
- clipes curtos (2 s): melspectrogram.onnx -> embedding_model.onnx, janelas de
  76 frames de mel com passo 8 -> [N, 16, 96]. O clipe ocupa o fim da janela de
  2 s e o resto e fundo (silencio baixo, ruido, jogo, musica);
- audio longo (conversa, jogo, musica): as features saem em streaming, uma
  linha [96] por chunk de 80 ms (1280 amostras), reproduzindo o estado interno
  do detector (buffer de 1760 amostras, 970 frames de mel, janela de 76).

Saidas em $GOL_DATA/features/:
  pos_train.npy  neg_train.npy  pos_test.npy      -> [N, 16, 96] float16
  stream_<cat>_<split>_features.npy               -> [M, 96] float16
  stream_<cat>_<split>_rms.npy                    -> [M] float32 (dBFS por chunk)
  stream_<cat>_<split>_meta.json                  -> fontes, horas, chunks
Categorias de audio longo: conversa (speech pt-BR), jogo (game), musica (music).
Split por arquivo/falante/video: nenhuma fonte aparece nos dois lados.

Uso:
  uv run python features.py --tudo
  uv run python features.py --curtos
  uv run python features.py --streaming --horas-avaliacao 8.5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import comum as C

CHUNK = 1280
MEL_WINDOW = 76
MEL_CONTEXT = 160 * 3
PASSO = 8
DIM = 96

FEAT = C.FEATURES


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# extração
# --------------------------------------------------------------------------- #
def sessao(caminho: Path):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.enable_cpu_mem_arena = False
    opts.log_severity_level = 3
    return ort.InferenceSession(str(caminho), sess_options=opts, providers=["CPUExecutionProvider"])


class Extrator:
    """Espelho de ronaldo/detector.WakeWord para a parte de features."""

    def __init__(self) -> None:
        self.mel = sessao(C.MODELS / "melspectrogram.onnx")
        self.emb = sessao(C.MODELS / "embedding_model.onnx")

    def melspec(self, audio: np.ndarray) -> np.ndarray:
        out = self.mel.run(None, {"input": audio.astype(np.float32)[None, :]})[0]
        return np.squeeze(out) / 10 + 2

    def embed(self, janelas: np.ndarray) -> np.ndarray:
        """janelas [N,76,32] -> [N,96]."""
        x = np.asarray(janelas, dtype=np.float32)[..., None]
        out = self.emb.run(None, {"input_1": x})[0]
        return np.asarray(out).reshape(len(janelas), DIM)


_EX: Extrator | None = None


def extrator() -> Extrator:
    global _EX
    if _EX is None:
        _EX = Extrator()
    return _EX


def _int16(x: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(x, dtype=np.float32) * 32767.0, -32768, 32767).astype(np.int16)


def features_clip(x: np.ndarray) -> np.ndarray:
    """Clipe float32 (2 s) -> [16,96] float32 (ultimas 16 janelas)."""
    ex = extrator()
    mels = ex.melspec(_int16(x))
    janelas = [mels[i : i + MEL_WINDOW] for i in range(0, len(mels), PASSO)
               if len(mels[i : i + MEL_WINDOW]) == MEL_WINDOW]
    if not janelas:
        return np.zeros((0, DIM), dtype=np.float32)
    feats = ex.embed(np.asarray(janelas))
    return feats[-16:] if len(feats) >= 16 else feats


def features_streaming_rms(x: np.ndarray) -> float:
    """RMS em dBFS de um bloco, mesma escala do detector (int16 / 32768)."""
    audio16 = _int16(x)
    r = float(np.sqrt(np.mean(np.square(audio16.astype(np.float64)))))
    return 20.0 * np.log10(max(r, 1e-9) / 32768.0)


def features_streaming(caminho: Path, bloco_seg: float = 300.0, lote: int = 2048,
                       dtype=np.float16):
    """Reproduz o streaming do detector: [96] por chunk de 80 ms + RMS dBFS."""
    import soundfile as sf

    ex = extrator()
    info = sf.info(str(caminho))
    if info.samplerate != C.SR or info.channels != 1:
        raise SystemExit(f"{caminho}: {info.samplerate} Hz, {info.channels} canais (precisa 16k mono)")

    raw = np.zeros(0, dtype=np.int16)
    mels = np.ones((MEL_WINDOW, 32), dtype=np.float32)
    restante = np.zeros(0, dtype=np.int16)
    janelas_lote: list[np.ndarray] = []
    feats: list[np.ndarray] = []
    rms: list[np.float32] = []

    def drenar(ultimo: bool = False) -> None:
        nonlocal janelas_lote
        if not janelas_lote:
            return
        if ultimo or len(janelas_lote) >= lote:
            out = ex.embed(np.asarray(janelas_lote, dtype=np.float32))
            feats.append(out.astype(dtype))
            janelas_lote = []

    with sf.SoundFile(str(caminho)) as f:
        while True:
            bloco = f.read(int(bloco_seg * C.SR), dtype="int16", always_2d=False)
            if bloco is None or len(bloco) == 0:
                break
            audio = np.concatenate([restante, np.asarray(bloco, dtype=np.int16)])
            n_chunks = len(audio) // CHUNK
            for i in range(n_chunks):
                pedaco = audio[i * CHUNK : (i + 1) * CHUNK]
                raw = np.concatenate([raw, pedaco])[-(CHUNK + MEL_CONTEXT):]
                mels = np.vstack([mels, ex.melspec(raw)])[-970:]
                janelas_lote.append(mels[-MEL_WINDOW:])
                r = float(np.sqrt(np.mean(np.square(pedaco.astype(np.float64)))))
                rms.append(np.float32(20.0 * np.log10(max(r, 1e-9) / 32768.0)))
                if len(janelas_lote) >= lote:
                    drenar()
            restante = audio[n_chunks * CHUNK :]
    drenar(ultimo=True)

    feats_arr = np.vstack(feats) if feats else np.zeros((0, DIM), np.float16)
    rms_arr = np.asarray(rms, dtype=np.float32)
    if len(feats_arr) != len(rms_arr):
        n = min(len(feats_arr), len(rms_arr))
        log(f"AVISO {caminho.name}: {len(feats_arr)} features != {len(rms_arr)} rms; cortando em {n}")
        feats_arr, rms_arr = feats_arr[:n], rms_arr[:n]
    return feats_arr, rms_arr


# --------------------------------------------------------------------------- #
# curtas: positivos e negativos sinteticos
# --------------------------------------------------------------------------- #
def _curtos_worker(args: tuple[str, list[str]]) -> tuple[str, np.ndarray]:
    nome, arquivos = args
    import soundfile as sf

    ex = extrator()
    saida = []
    for caminho in arquivos:
        x, sr = sf.read(caminho, dtype="float32", always_2d=True)
        x = x.mean(axis=1)
        if sr != C.SR:
            x = C.resample(x, sr)
        feats = features_clip(x)
        if len(feats) == 16:
            saida.append(feats.astype(np.float16))
    return nome, np.asarray(saida, dtype=np.float16) if saida else np.zeros((0, 16, DIM), np.float16)


def converter_curtos(entrada: Path, saida: Path, workers: int = 8) -> np.ndarray:
    arquivos = sorted(entrada.glob("*.wav"))
    if not arquivos:
        raise SystemExit(f"sem wavs em {entrada}")
    if saida.exists():
        a = np.load(saida)
        if len(a) == len(arquivos):
            log(f"{saida.name}: ja existe com {len(a)} amostras")
            return a
    log(f"{saida.name}: {len(arquivos)} clipes")
    partes = [(str(entrada), arquivos[i::workers]) for i in range(workers)]
    pedacos: dict[str, np.ndarray] = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, (nome, arr) in enumerate(pool.map(_curtos_worker, partes), 1):
            pedacos[nome] = arr
            log(f"  worker {i}/{workers}: {len(arr)} amostras ({time.time()-t0:.0f}s)")
    arr = np.concatenate([pedacos[nome] for nome, _ in partes], axis=0) if pedacos else np.zeros((0, 16, DIM), np.float16)
    saida.parent.mkdir(parents=True, exist_ok=True)
    np.save(saida, arr)
    log(f"{saida.name}: {arr.shape} {arr.dtype}")
    return arr


# --------------------------------------------------------------------------- #
# split de audio longo por fonte
# --------------------------------------------------------------------------- #
def _chave_fonte(categoria: str, caminho: Path) -> str:
    if categoria == "speech_ptbr":
        return caminho.stem.split("_")[0]  # falante MLS
    return caminho.stem  # video ou faixa


def planejar_split(categoria: str, horas_avaliacao: float, seed: int = 7) -> dict:
    """Divide arquivos (por fonte) em treino/avaliacao sem sobreposicao."""
    pasta = C.RAW / categoria / "wav"
    if not pasta.exists():
        pasta = C.RAW / categoria
    arquivos = sorted(pasta.glob("*.wav"))
    if not arquivos:
        raise SystemExit(f"sem wavs para {categoria}")
    grupos: dict[str, list[Path]] = {}
    for a in arquivos:
        grupos.setdefault(_chave_fonte(categoria, a), []).append(a)
    chaves = sorted(grupos)
    random.Random(seed).shuffle(chaves)

    import soundfile as sf

    def dur_h(p: Path) -> float:
        info = sf.info(str(p))
        return info.frames / info.samplerate / 3600.0

    total = sum(dur_h(a) for a in arquivos)
    avaliacao: list[Path] = []
    treino: list[Path] = []
    h_aval = 0.0
    for chave in chaves:
        d = sum(dur_h(a) for a in grupos[chave])
        if h_aval < horas_avaliacao:
            avaliacao.extend(grupos[chave])
            h_aval += d
        else:
            treino.extend(grupos[chave])
    h_treino = sum(dur_h(a) for a in treino)
    log(f"{categoria}: total {total:.2f} h -> avaliacao {h_aval:.2f} h / treino {h_treino:.2f} h")
    if h_aval < 8.0:
        raise SystemExit(f"{categoria}: avaliacao com {h_aval:.2f} h (< 8 h)")
    if h_treino < 8.0:
        raise SystemExit(f"{categoria}: treino com {h_treino:.2f} h (< 8 h)")
    return {"categoria": categoria, "total_h": round(total, 3),
            "avaliacao_h": round(h_aval, 3), "treino_h": round(h_treino, 3),
            "avaliacao": [str(a) for a in sorted(avaliacao)],
            "treino": [str(a) for a in sorted(treino)]}


def converter_streaming(categoria: str, plano: dict) -> list[dict]:
    registros = []
    for split, arquivos in (("treino", plano["treino"]), ("avaliacao", plano["avaliacao"])):
        saida_f = FEAT / f"stream_{categoria}_{split}_features.npy"
        saida_r = FEAT / f"stream_{categoria}_{split}_rms.npy"
        saida_m = FEAT / f"stream_{categoria}_{split}_meta.json"
        if saida_f.exists() and saida_m.exists():
            meta = json.loads(saida_m.read_text())
            log(f"{saida_f.name}: ja existe ({meta['chunks']} chunks, {meta['horas']:.2f} h)")
            registros.append(meta)
            continue
        feats, rms = [], []
        t0 = time.time()
        for i, arquivo in enumerate(arquivos, 1):
            f, r = features_streaming(Path(arquivo))
            feats.append(f)
            rms.append(r)
            if i % 5 == 0 or i == len(arquivos):
                log(f"  {categoria}/{split}: {i}/{len(arquivos)} ({time.time()-t0:.0f}s)")
        feats_arr = np.concatenate(feats) if feats else np.zeros((0, DIM), np.float16)
        rms_arr = np.concatenate(rms) if rms else np.zeros((0,), np.float32)
        FEAT.mkdir(parents=True, exist_ok=True)
        np.save(saida_f, feats_arr)
        np.save(saida_r, rms_arr)
        meta = {
            "arquivo_features": str(saida_f.relative_to(C.ROOT)),
            "arquivo_rms": str(saida_r.relative_to(C.ROOT)),
            "categoria": categoria,
            "split": split,
            "chunks": int(len(feats_arr)),
            "horas": round(len(feats_arr) * 0.08 / 3600.0, 3),
            "fontes": len(arquivos),
            "shape": list(feats_arr.shape),
            "dtype": str(feats_arr.dtype),
            "arquivos": [str(Path(a).name) for a in arquivos],
        }
        saida_m.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        log(f"{saida_f.name}: {feats_arr.shape} ({meta['horas']:.2f} h)")
        registros.append(meta)
    return registros


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tudo", action="store_true")
    ap.add_argument("--curtos", action="store_true")
    ap.add_argument("--streaming", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--horas-avaliacao", type=float, default=8.5)
    args = ap.parse_args()
    if not (args.tudo or args.curtos or args.streaming):
        ap.error("escolha --tudo, --curtos ou --streaming")

    FEAT.mkdir(parents=True, exist_ok=True)
    planos = []
    if args.tudo or args.streaming:
        for categoria in ("speech_ptbr", "game", "music"):
            plano = planejar_split(categoria, args.horas_avaliacao)
            planos.append(plano)
            converter_streaming(categoria, plano)
        (FEAT / "split_streaming.json").write_text(
            json.dumps(planos, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.tudo or args.curtos:
        converter_curtos(C.WORK / "pos_train", FEAT / "pos_train.npy", args.workers)
        converter_curtos(C.WORK / "neg_train", FEAT / "neg_train.npy", args.workers)
        converter_curtos(C.WORK / "pos_test", FEAT / "pos_test.npy", args.workers)
    log("pronto")


if __name__ == "__main__":
    main()
