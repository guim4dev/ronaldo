#!/usr/bin/env python3
"""Baixa tudo o que o modelo gol_grito precisa para ~/data/gol/raw.

Nada de audio entra no git: este script so grava em $GOL_DATA (padrao
~/data/gol). E idempotente: cada etapa pula o que ja esta no lugar. Cada
download fica registrado em $GOL_DATA/FONTES.md (URL, licenca, tamanho).

Etapas (--etapa):
  openwakeword  features ACAV100M (17 GB) + validation_set_features.npy
  piper         binario piper + vozes pt_BR (faber, edresson, cadu, jeff)
  rir           270 RIRs MIT (16 kHz) do dataset do openWakeWord
  noise         ESC-50 (ruido ambiente) -> wav 16 kHz mono
  music         FMA small (6 shards, ~26 h) -> wav 16 kHz mono
  speech        MLS portugues: tarballs de falantes ate >= 18 h -> wav 16 kHz mono
  game          futebol de videogame via yt-dlp (Rematch/FIFA sem narracao) >= 16 h
  gol_real      narracoes de gol brasileiras via yt-dlp, recortadas em clipes <= 3 s
  all           todas as etapas, nesta ordem

Uso:
  uv run python download.py --etapa all
  uv run python download.py --etapa music
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(os.environ.get("GOL_DATA", Path.home() / "data" / "gol")).expanduser()
RAW = ROOT / "raw"
LOGS = ROOT / "logs"
FONTES_JSONL = ROOT / "fontes.jsonl"
SR = 16000

PIPER_VOZES_TREINO = ["faber", "edresson", "cadu"]
PIPER_VOZES_TESTE = ["jeff"]
PIPER_RELEASE = (
    "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"
)

HF = "https://huggingface.co"
HF_DATASETS = f"{HF}/datasets"


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def registrar(titulo: str, url: str, destino: Path, licenca: str = "", nota: str = "") -> None:
    """Registra uma fonte em fontes.jsonl (uma linha por URL)."""
    ROOT.mkdir(parents=True, exist_ok=True)
    rel = str(destino.relative_to(ROOT)) if destino.is_absolute() and ROOT in destino.parents else str(destino)
    linha = {
        "data": date.today().isoformat(),
        "titulo": titulo,
        "url": url,
        "destino": rel,
        "licenca": licenca,
        "nota": nota,
    }
    existentes = set()
    if FONTES_JSONL.exists():
        for ln in FONTES_JSONL.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    d = json.loads(ln)
                    existentes.add((d.get("url"), d.get("destino")))
                except json.JSONDecodeError:
                    pass
    if (url, rel) not in existentes:
        with FONTES_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")


FONTES_PRINCIPAIS = [
    ("openWakeWord: features ACAV100M (5.625 M clipes de 2 s)",
     "https://huggingface.co/datasets/davidscripka/openwakeword_features", "CC-BY 4.0"),
    ("openWakeWord: validation_set_features (~10.7 h de streaming)",
     "https://huggingface.co/datasets/davidscripka/openwakeword_features", "CC-BY 4.0"),
    ("Piper: binario 2023.11.14-2 (linux x86_64 + espeak-ng)",
     "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz", "MIT / GPL (espeak-ng)"),
    ("Piper: vozes pt_BR faber, edresson, cadu, jeff",
     "https://huggingface.co/rhasspy/piper-voices", "MIT / ver MODEL_CARD de cada voz"),
    ("MIT environmental impulse responses (270 RIRs a 16 kHz)",
     "https://huggingface.co/datasets/davidscripka/MIT_environmental_impulse_responses", "MIT IR Survey"),
    ("ESC-50 (2 000 clipes de ruido ambiente)",
     "https://huggingface.co/datasets/ashraq/esc50", "CC-BY-NC 3.0"),
    ("FMA small (8 000 faixas de 30 s; 6 shards usados)",
     "https://huggingface.co/datasets/benjamin-paine/free-music-archive-small", "CC-BY / CC-BY-SA / CC0 por faixa"),
    ("MLS portugues (tarballs de falante do OPUS)",
     "https://huggingface.co/datasets/facebook/multilingual_librispeech", "CC-BY 4.0"),
    ("edge-tts (vozes reservadas de teste: pt-BR Francisca/Antonio/Thalita, pt-PT Raquel/Duarte)",
     "https://pypi.org/project/edge-tts/", "termos do servico Microsoft"),
    ("Audio de jogo de futebol de videogame (yt-dlp, bestaudio 16 kHz mono)",
     "https://www.youtube.com (videos listados abaixo)", "conteudo de terceiros, uso local"),
    ("Narracoes de gol brasileiras recortadas (yt-dlp, clipes <= 3 s)",
     "https://www.youtube.com (videos listados abaixo)", "conteudo de terceiros, uso local"),
]

DERIVADOS = [
    ("raw/music/wav/", "3 127 faixas de 30 s decodificadas de raw/music/parquet (16 kHz mono)"),
    ("raw/noise/wav/", "2 000 clipes de 5 s decodificados de raw/noise/parquet (16 kHz mono)"),
    ("raw/speech_ptbr/wav/", "5 000 audios do MLS portugues (tarballs em raw/speech_ptbr/tar)"),
    ("raw/gol_real/clips/", "125 trechos de 2,4 s recortados nos picos de volume das narracoes"),
    ("work/tts_positivos/", "bases TTS do Piper (voz x texto x parametros)"),
    ("work/tts_negativos/", "bases TTS das frases de fala normal e das palavras gritadas"),
    ("work/pos_train/", "20 000 positivos de 2 s com aumento de grito"),
    ("work/pos_test/", "1 000 positivos de teste (vozes reservadas; metade com jogo)"),
    ("work/neg_train/", "20 000 negativos de 2 s (fala normal + palavras gritadas)"),
    ("features/", "features openWakeWord (.npy) e RMS dBFS por chunk"),
]


def escrever_fontes() -> None:
    """Renderiza $GOL_DATA/FONTES.md: fontes principais, derivados e videos usados."""
    if not FONTES_JSONL.exists():
        return
    videos_jogo = set()
    videos_gol = set()
    contagem = {"rir": 0, "piper": 0, "mls": 0, "parquet": 0}
    for ln in FONTES_JSONL.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        destino = ROOT / d["destino"] if not Path(d["destino"]).is_absolute() else Path(d["destino"])
        if not destino.exists():
            continue
        if d["destino"].startswith("raw/game/") and "youtube.com/watch" in d.get("url", ""):
            videos_jogo.add(d["url"])
        if d["destino"].startswith("raw/gol_real/videos/") and "youtube.com/watch" in d.get("url", ""):
            videos_gol.add(d["url"])
        if d["destino"].startswith("raw/rir/"):
            contagem["rir"] += 1
        if d["destino"].startswith("raw/piper/vozes/"):
            contagem["piper"] += 1
        if "mls_portuguese" in d.get("url", ""):
            contagem["mls"] += 1
        if "/parquet/" in d["destino"]:
            contagem["parquet"] += 1

    out = [
        "# Fontes dos dados de treino e avaliacao — gol_grito",
        "",
        "Gerado por `training/gol/download.py`. Todo audio vive em `~/data/gol/` (fora do git).",
        "Repositorio publico: nenhum arquivo de audio e versionado.",
        "",
        "## Fontes principais",
        "",
        "| fonte | URL | licenca |",
        "|---|---|---|",
    ]
    for titulo, url, licenca in FONTES_PRINCIPAIS:
        out.append(f"| {titulo} | <{url}> | {licenca} |")

    out += ["", "## Arquivos derivados (sem URL propria)", "",
            "| caminho | o que |", "|---|---|"]
    for caminho, descricao in DERIVADOS:
        if (ROOT / caminho.rstrip("/")).exists():
            out.append(f"| `{caminho}` | {descricao} |")

    out += [
        "",
        "## Downloads conferidos",
        "",
        f"- RIRs MIT: {contagem['rir']} arquivos de 16 kHz.",
        f"- Vozes Piper: {contagem['piper']} arquivos (.onnx, .onnx.json, MODEL_CARD).",
        f"- Tarballs do MLS portugues: {contagem['mls']}.",
        f"- Shards parquet (FMA e ESC-50): {contagem['parquet']}.",
        f"- Videos de jogo de videogame: {len(videos_jogo)}.",
        f"- Videos de narracao de gol: {len(videos_gol)}.",
        "",
        "## Videos do YouTube usados",
        "",
        "### Jogo de videogame (audio de fundo e avaliacao)",
        "",
    ]
    for url in sorted(videos_jogo):
        out.append(f"- {url}")
    out += ["", "### Narracoes de gol (avaliacao; nunca no git)", ""]
    for url in sorted(videos_gol):
        out.append(f"- {url}")
    out += [
        "",
        "## Ferramentas",
        "",
        "- `piper` 2023.11.14-2 (MIT) e `espeak-ng` (GPL).",
        "- `edge-tts` (vozes da Microsoft; so no conjunto de teste).",
        "- `yt-dlp` (Unlicense) para os audios de jogo e narrativas.",
        "- `ffmpeg` (LGPL/GPL) para rubberband, resample e recorte.",
    ]
    (ROOT / "FONTES.md").write_text("\n".join(out) + "\n", encoding="utf-8")


def tamanho(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return -1


def curl(url: str, destino: Path, esperado: int | None = None, titulo: str = "", licenca: str = "") -> Path:
    """Baixa com curl -L -C - (retoma download interrompido)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    atual = tamanho(destino)
    if esperado is not None and atual == esperado:
        log(f"ja existe {destino.name} ({atual} bytes)")
        registrar(titulo or destino.name, url, destino, licenca)
        return destino
    if esperado is None and atual > 0:
        log(f"ja existe {destino.name} ({atual} bytes)")
        registrar(titulo or destino.name, url, destino, licenca)
        return destino
    for tentativa in range(2):
        log(f"baixando {url} -> {destino}" + (" (retomando)" if tentativa else ""))
        cmd = ["curl", "-sSL", "--fail", "--retry", "6", "--retry-delay", "3",
               "--retry-all-errors", "-C", "-", "-o", str(destino), url]
        with subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as p:
            _, err = p.communicate()
            if p.returncode != 0:
                raise SystemExit(f"curl falhou ({p.returncode}) em {url}: {err.decode(errors='replace')[-800:]}")
        if esperado is None or tamanho(destino) == esperado:
            registrar(titulo or destino.name, url, destino, licenca)
            return destino
        log(f"tamanho errado ({tamanho(destino)} != {esperado}); baixando de novo do zero")
        destino.unlink(missing_ok=True)
    raise SystemExit(f"{destino}: nao chegou em {esperado} bytes")


def baixar_partes(url: str, destino: Path, tamanho_total: int, partes: int = 12,
                  paralelo: int = 8, titulo: str = "", licenca: str = "") -> Path:
    """Baixa um arquivo grande em ranges paralelos (curl -r), depois concatena.

    O CDN do HF limita ~1 MB/s por conexao para este arquivo; 8 conexoes
    rendem ~7-8 MB/s. Retoma por parte: parte com tamanho certo e reusada.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    if tamanho(destino) == tamanho_total:
        log(f"ja existe {destino.name} ({tamanho_total} bytes)")
        registrar(titulo or destino.name, url, destino, licenca)
        return destino
    tmp = destino.with_name(destino.name + ".partes")
    tmp.mkdir(exist_ok=True)
    tam = (tamanho_total + partes - 1) // partes
    faixas = []
    for i in range(partes):
        ini = i * tam
        fim = min(tamanho_total - 1, ini + tam - 1)
        if ini > fim:
            break
        faixas.append((i, ini, fim, tmp / f"{i:03d}.part"))
    pendentes = []
    for i, ini, fim, arq in faixas:
        esperado = fim - ini + 1
        if tamanho(arq) == esperado:
            continue
        log(f"parte {i:02d}: bytes {ini}-{fim} ({(esperado/1e9):.2f} GB)")
        pendentes.append(
            subprocess.Popen(
                ["curl", "-sSL", "--fail", "-r", f"{ini}-{fim}", "-o", str(arq), url],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        )
        while len(pendentes) >= paralelo:
            for p in list(pendentes):
                if p.poll() is not None:
                    if p.returncode != 0:
                        err = p.stderr.read().decode(errors="replace")[-500:] if p.stderr else ""
                        raise SystemExit(f"curl range falhou: {err}")
                    p.stderr.close()
                    pendentes.remove(p)
            if len(pendentes) >= paralelo:
                time.sleep(2)
    for p in pendentes:
        p.wait()
        if p.returncode != 0:
            raise SystemExit("curl range falhou no final")
        if p.stderr:
            p.stderr.close()
    for i, ini, fim, arq in faixas:
        esperado = fim - ini + 1
        if tamanho(arq) != esperado:
            raise SystemExit(f"parte {arq} tem {tamanho(arq)} bytes, esperava {esperado}")
    log("concatenando partes")
    with destino.open("wb") as out:
        for _, _, _, arq in faixas:
            with arq.open("rb") as f:
                shutil.copyfileobj(f, out, length=16 * 1024 * 1024)
    if tamanho(destino) != tamanho_total:
        raise SystemExit(f"{destino} tem {tamanho(destino)} bytes, esperava {tamanho_total}")
    shutil.rmtree(tmp, ignore_errors=True)
    registrar(titulo or destino.name, url, destino, licenca)
    return destino


def hf_get(repo: str, filename: str, destino_dir: Path, repo_type: str = "dataset",
           esperado: int | None = None, titulo: str = "", licenca: str = "") -> Path:
    """Baixa um arquivo do Hugging Face Hub direto do CDN (curl), achatando o nome.

    Usa curl em vez de hf_hub_download: o backend Xet desta maquina fica
    parado em 0 byte em alguns arquivos grandes, enquanto o resolve/CDN
    entrega estavel. Retoma com -C - e confere o tamanho quando conhecido.
    """
    prefixo = "datasets" if repo_type == "dataset" else ""
    url = f"{HF}/{prefixo + '/' if prefixo else ''}{repo}/resolve/main/{filename}"
    return curl(url, destino_dir / Path(filename).name, esperado=esperado,
                titulo=titulo, licenca=licenca)


def semear(vetor: np.ndarray) -> np.ndarray:
    """float -> int16 com saturacao (formato do pipeline)."""
    return np.clip(vetor, -1.0, 1.0).__mul__(32767).astype(np.int16)


def ler_audio(p: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    x, sr = sf.read(str(p), dtype="float32", always_2d=True)
    return x.mean(axis=1), int(sr)


def resample(x: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    if sr_in == sr_out:
        return x.astype(np.float32, copy=False)
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(int(sr_in), int(sr_out))
    return resample_poly(x.astype(np.float32), sr_out // g, sr_in // g).astype(np.float32)


def salvar_wav16(p: Path, x: np.ndarray, sr: int = SR) -> None:
    import soundfile as sf

    p.parent.mkdir(parents=True, exist_ok=True)
    x = np.asarray(x, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    sf.write(str(p), np.clip(x, -1.0, 1.0), sr, subtype="PCM_16")


def duracao(p: Path) -> float:
    import soundfile as sf

    try:
        info = sf.info(str(p))
        return float(info.frames) / float(info.samplerate)
    except Exception:
        return 0.0


# --------------------------------------------------------------------------- #
# etapas
# --------------------------------------------------------------------------- #
def etapa_openwakeword() -> None:
    """Features pre-computadas do openWakeWord (negativos gerais)."""
    dest = RAW / "openwakeword"
    url = f"{HF_DATASETS}/davidscripka/openwakeword_features/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
    baixar_partes(
        url,
        dest / "openwakeword_features_ACAV100M_2000_hrs_16bit.npy",
        17280000128,
        titulo="openWakeWord: features ACAV100M (2000 h, 5.625 M clipes de 2 s)",
        licenca="CC-BY 4.0 (ACAV100M) — uso conforme o openWakeWord",
    )
    hf_get("davidscripka/openwakeword_features", "validation_set_features.npy", dest,
           esperado=184836608, titulo="openWakeWord: features de validacao (~10,7 h, streaming 80 ms)",
           licenca="CC-BY 4.0 — conjunto de validacao do openWakeWord")
    for f in sorted(dest.glob("*.npy")):
        a = np.load(f, mmap_mode="r")
        log(f"{f.name}: shape={a.shape} dtype={a.dtype}")


def etapa_piper() -> None:
    """Binario piper + todas as qualidades das vozes pt_BR."""
    dest_bin = RAW / "piper"
    tar = dest_bin / "piper_linux_x86_64.tar.gz"
    if not (dest_bin / "piper" / "piper").exists():
        curl(PIPER_RELEASE, tar, titulo="piper 2023.11.14-2 (binario linux x86_64 + espeak-ng)",
             licenca="MIT (piper) / GPL (espeak-ng)")
        log("extraindo piper")
        with tarfile.open(tar) as tf:
            tf.extractall(dest_bin)
    else:
        registrar("piper 2023.11.14-2 (binario linux x86_64)", PIPER_RELEASE, dest_bin / "piper" / "piper",
                  "MIT / GPL (espeak-ng)")

    voices = hf_get("rhasspy/piper-voices", "voices.json", dest_bin / "meta",
                    repo_type="model", titulo="rhasspy/piper-voices: catalogo de vozes",
                    licenca="MIT (vozes: CC-BY / dominio publico conforme MODEL_CARD)")
    import json as _json

    catalogo = _json.loads(Path(voices).read_text(encoding="utf-8"))
    desejadas = PIPER_VOZES_TREINO + PIPER_VOZES_TESTE
    baixadas = 0
    for chave, meta in sorted(catalogo.items()):
        # chave no catalogo: pt_BR-<voz>-<qualidade> (ex.: pt_BR-faber-medium)
        if not chave.startswith("pt_BR-"):
            continue
        partes = chave.split("-")
        if len(partes) < 3 or partes[1] not in desejadas:
            continue
        voz, qualidade = partes[1], partes[2]
        for nome_arquivo, info in meta.get("files", {}).items():
            if not (nome_arquivo.endswith(".onnx") or nome_arquivo.endswith(".onnx.json") or nome_arquivo.endswith("MODEL_CARD")):
                continue
            destino = RAW / "piper" / "vozes" / voz / qualidade
            hf_get("rhasspy/piper-voices", nome_arquivo, destino, repo_type="model",
                   titulo=f"Piper pt_BR {voz}/{qualidade}: {Path(nome_arquivo).name}",
                   licenca="ver MODEL_CARD")
            baixadas += 1
    log(f"vozes pt_BR baixadas: {baixadas} arquivos para {desejadas}")


def etapa_rir() -> None:
    """RIRs MIT (16 kHz) usadas pelo openWakeWord."""
    from huggingface_hub import HfApi

    api = HfApi()
    arquivos = [
        f for f in api.list_repo_files("davidscripka/MIT_environmental_impulse_responses", repo_type="dataset")
        if f.startswith("16khz/") and f.endswith(".wav")
    ]
    log(f"RIRs: {len(arquivos)} arquivos")
    dest = RAW / "rir"
    for i, arq in enumerate(sorted(arquivos), 1):
        hf_get("davidscripka/MIT_environmental_impulse_responses", arq, dest,
               titulo="MIT environmental impulse responses (16 kHz)", licenca="MIT IR Survey (uso livre)")
        if i % 50 == 0:
            log(f"  {i}/{len(arquivos)} RIRs")


def _decodificar_parquet_audio(parquets: list[Path], destino: Path, prefixo: str,
                               max_seg: float | None = None, min_seg: float = 0.0) -> float:
    """Decodifica colunas de audio (struct bytes/path) de parquets em wav 16 kHz mono.

    Le em lotes (iter_batches) para nao carregar um shard inteiro na RAM.
    Retorna as horas gravadas.
    """
    import pyarrow.parquet as pq
    import soundfile as sf

    destino.mkdir(parents=True, exist_ok=True)
    marcador = destino / ".pronto"
    if marcador.exists():
        horas = sum(duracao(p) for p in destino.glob("*.wav")) / 3600.0
        log(f"{destino}: ja decodificado ({len(list(destino.glob('*.wav')))} wavs, {horas:.2f} h)")
        return horas
    horas = 0.0
    indice_global = 0
    for pq_path in parquets:
        pf = pq.ParquetFile(pq_path)
        colunas = pf.schema_arrow.names
        col_audio = next((c for c in ("audio", "audio_file", "file") if c in colunas), None)
        if col_audio is None:
            raise SystemExit(f"{pq_path}: colunas {colunas} sem coluna de audio")
        col_id = next((c for c in ("__key__", "filename", "title") if c in colunas), None)
        ler = [col_audio] + ([col_id] if col_id else [])
        log(f"{pq_path.name}: {pf.metadata.num_rows} registros")
        indice = 0
        for lote in pf.iter_batches(batch_size=32, columns=ler):
            col = lote.column(col_audio).to_pylist()
            ids = lote.column(col_id).to_pylist() if col_id else [None] * len(col)
            for ident, item in zip(ids, col):
                # nome deterministico: prefixo + indice global (ordem de leitura
                # dos parquets). Assim uma segunda execucao pula tudo e nao
                # duplica o acervo.
                indice += 1
                saida = destino / f"{prefixo}_{indice_global:05d}.wav"
                indice_global += 1
                if saida.exists():
                    horas += duracao(saida) / 3600.0
                    continue
                if item is None:
                    continue
                dados = item.get("bytes") if isinstance(item, dict) else item
                if not dados:
                    continue
                try:
                    x, sr = sf.read(io.BytesIO(dados), dtype="float32", always_2d=True)
                except Exception as exc:  # noqa: BLE001
                    log(f"  pulando {nome}: {exc}")
                    continue
                x = x.mean(axis=1)
                x = resample(x, sr)
                dur = len(x) / SR
                if dur < max(min_seg, 0.5) or (max_seg is not None and dur > max_seg):
                    continue
                salvar_wav16(saida, x)
                horas += dur / 3600.0
    marcador.write_text(str(indice_global), encoding="utf-8")
    return horas


def etapa_noise() -> None:
    """ESC-50 -> ruido ambiente 16 kHz mono."""
    dest_parquet = RAW / "noise" / "parquet"
    for nome, tamanho_esperado in [
        ("train-00000-of-00002-2f1ab7b824ec751f.parquet", 386533721),
        ("train-00001-of-00002-27425e5c1846b494.parquet", 386533722),
    ]:
        hf_get("ashraq/esc50", f"data/{nome}", dest_parquet,
               esperado=None, titulo="ESC-50 (ruido ambiente, 2000 clipes de 5 s)", licenca="CC-BY-NC 3.0")
    parquets = sorted(dest_parquet.glob("*.parquet"))
    if not parquets:
        raise SystemExit("ESC-50 nao baixado")
    destino = RAW / "noise" / "wav"
    if len(list(destino.glob("*.wav"))) >= 1900:
        log(f"ESC-50 ja decodificado ({len(list(destino.glob('*.wav')))} wavs)")
        return
    horas = _decodificar_parquet_audio(parquets, destino, "esc50")
    log(f"ESC-50: {horas:.2f} h de ruido em {destino}")


def etapa_music() -> None:
    """FMA small (shards escolhidos) -> wav 16 kHz mono."""
    dest_parquet = RAW / "music" / "parquet"
    shards = [0, 1, 2, 3, 4, 5]
    for i in shards:
        nome = f"data/train-{i:05d}-of-00015.parquet"
        hf_get("benjamin-paine/free-music-archive-small", nome, dest_parquet,
               titulo="FMA small (Free Music Archive, 8000 faixas de 30 s)",
               licenca="FMA: CC-BY / CC-BY-SA / CC0 por faixa")
    parquets = [dest_parquet / f"train-{i:05d}-of-00015.parquet" for i in shards]
    parquets = [p for p in parquets if p.exists()]
    destino = RAW / "music" / "wav"
    horas = _decodificar_parquet_audio(parquets, destino, "fma", max_seg=40.0)
    log(f"FMA: {horas:.2f} h de musica em {destino}")


def etapa_speech() -> None:
    """MLS portugues: baixa tarballs de falantes (maiores primeiro) ate >= 18 h."""
    from huggingface_hub import HfApi

    api = HfApi()
    repo = "facebook/multilingual_librispeech"
    arqs = [
        f for f in api.list_repo_files(repo, repo_type="dataset")
        if f.startswith("data/mls_portuguese/train/audio/") and f.endswith(".tar.gz")
    ]
    # Ordena por tamanho decrescente usando a API de tree (com size).
    entradas = api.list_repo_tree(repo, path_in_repo="data/mls_portuguese/train/audio", repo_type="dataset")
    tamanhos = {e.path: getattr(e, "size", 0) for e in entradas if getattr(e, "path", "").endswith(".tar.gz")}
    arqs.sort(key=lambda a: tamanhos.get(a, 0), reverse=True)
    log(f"MLS pt: {len(arqs)} tarballs de falante (total {sum(tamanhos.values())/1e9:.1f} GB)")

    dest_tar = RAW / "speech_ptbr" / "tar"
    dest_wav = RAW / "speech_ptbr" / "wav"
    dest_wav.mkdir(parents=True, exist_ok=True)
    horas = sum(duracao(p) for p in dest_wav.glob("*.wav")) / 3600.0
    log(f"MLS pt: ja decodificado {horas:.2f} h")
    for arq in arqs:
        if horas >= 18.0:
            break
        tar_path = hf_get(repo, arq, dest_tar, esperado=tamanhos.get(arq),
                          titulo=f"MLS portugues: {Path(arq).name}",
                          licenca="CC-BY 4.0 (MLS/OPUS)")
        with tarfile.open(tar_path) as tf:
            membros = [m for m in tf.getmembers() if m.name.endswith(".flac")]
            for m in membros:
                saida = dest_wav / (Path(m.name).stem + ".wav")
                if saida.exists():
                    horas += duracao(saida) / 3600.0
                    continue
                f = tf.extractfile(m)
                if f is None:
                    continue
                x, sr = __import__("soundfile").read(io.BytesIO(f.read()), dtype="float32", always_2d=True)
                x = x.mean(axis=1)
                x = resample(x, sr)
                if len(x) < SR * 0.4:
                    continue
                salvar_wav16(saida, x)
                horas += len(x) / SR / 3600.0
        log(f"MLS pt: {horas:.2f} h apos {Path(arq).name}")
    if horas < 16:
        raise SystemExit(f"MLS pt rendeu so {horas:.2f} h (precisa >= 16 h)")
    log(f"MLS pt pronto: {horas:.2f} h")


def _ytdlp() -> str:
    for nome in ("yt-dlp",):
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    raise SystemExit("yt-dlp nao encontrado no PATH")


def _yt_busca(consulta: str, n: int = 8) -> list[dict]:
    cmd = [
        _ytdlp(), "--no-warnings", "--flat-playlist",
        "--print", "%(id)s\t%(duration)s\t%(title)s",
        f"ytsearch{n}:{consulta}",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    itens = []
    for linha in out.stdout.splitlines():
        partes = linha.split("\t")
        if len(partes) < 3:
            continue
        try:
            dur = float(partes[1])
        except ValueError:
            dur = 0.0
        itens.append({"id": partes[0], "dur": dur, "titulo": partes[2]})
    return itens


def _yt_audio(video_id: str, destino: Path) -> Path:
    """Baixa so o audio e converte para wav 16 kHz mono."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.stat().st_size > 1000:
        return destino
    tmp = destino.parent / f"{video_id}.%(ext)s"
    cmd = [
        _ytdlp(), "--no-warnings", "--no-playlist",
        "--extractor-args", "youtube:player_client=android",
        "-f", "18",
        "-x", "--audio-format", "wav",
        "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1 -sample_fmt s16",
        "-o", str(tmp), f"https://www.youtube.com/watch?v={video_id}",
    ]
    log(f"yt-dlp {video_id} -> {destino.name}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"  falhou {video_id}: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}")
        return destino
    # yt-dlp grava <id>.wav
    candidato = destino.parent / f"{video_id}.wav"
    if candidato.exists() and candidato != destino:
        candidato.replace(destino)
    if destino.exists():
        registrar(f"YouTube {video_id} (audio de jogo)", f"https://www.youtube.com/watch?v={video_id}",
                  destino, "conteudo de terceiros, uso local para avaliacao/treino")
    return destino


def etapa_game() -> None:
    """Futebol de videogame sem narracao (Rematch primeiro) >= 16 h."""
    destino = RAW / "game"
    destino.mkdir(parents=True, exist_ok=True)
    horas = sum(duracao(p) for p in destino.glob("*.wav")) / 3600.0
    log(f"jogo: {horas:.2f} h ja baixadas")
    consultas = [
        "REMATCH gameplay no commentary",
        "REMATCH full match gameplay",
        "EA FC 25 gameplay no commentary full match",
        "FIFA 23 gameplay no commentary",
        "eFootball 2025 gameplay no commentary",
        "football video game gameplay longplay no commentary",
    ]
    vistos: set[str] = set()
    candidatos: list[dict] = []
    for consulta in consultas:
        for item in _yt_busca(consulta, n=8):
            if item["id"] in vistos:
                continue
            vistos.add(item["id"])
            titulo = item["titulo"].lower()
            if any(x in titulo for x in ("trailer", "review", "reaction", "short")):
                continue
            if item["dur"] < 600 or item["dur"] > 5 * 3600:
                continue
            candidatos.append(item)
    candidatos.sort(key=lambda x: -x["dur"])
    log(f"jogo: {len(candidatos)} candidatos, alvo 16 h")
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    with ThreadPoolExecutor(max_workers=2) as pool:
        fila = list(candidatos)
        pendentes = {}
        while (fila or pendentes) and horas < 16.3:
            while fila and len(pendentes) < 2:
                item = fila.pop(0)
                if (destino / f"{item['id']}.wav").exists():
                    continue
                pendentes[pool.submit(_yt_audio, item["id"], destino / f"{item['id']}.wav")] = item
            if not pendentes:
                break
            prontos, _ = wait(pendentes, return_when=FIRST_COMPLETED)
            for f in prontos:
                item = pendentes.pop(f)
                p = f.result()
                if p.exists():
                    horas += duracao(p) / 3600.0
                    log(f"jogo: {horas:.2f} h ({item['id']})")
            if horas >= 16.3:
                for f in pendentes:
                    f.cancel()
                break
    if horas < 16:
        raise SystemExit(f"jogo rendeu so {horas:.2f} h (precisa >= 16 h)")
    log(f"jogo pronto: {horas:.2f} h")


def _envelope_rms(x: np.ndarray, janela: int, passo: int) -> np.ndarray:
    if len(x) < janela:
        return np.zeros(0, dtype=np.float32)
    n = 1 + (len(x) - janela) // passo
    idx = np.arange(n)[:, None] * passo + np.arange(janela)[None, :]
    blocos = x[idx]
    return np.sqrt((blocos.astype(np.float64) ** 2).mean(axis=1)).astype(np.float32)


def etapa_gol_real() -> None:
    """Narracoes de gol (videos publicos), recortadas em clipes <= 3 s."""
    destino = RAW / "gol_real"
    videos = destino / "videos"
    clips = destino / "clips"
    videos.mkdir(parents=True, exist_ok=True)
    clips.mkdir(parents=True, exist_ok=True)
    consultas = [
        'narração gol brasileiro "GOOOOL"',
        "gooool narrador brasileiro compilado",
        "narracoes de gol historicas brasileiras",
        "galvao bueno gol narracao",
        "gol do flamengo narracao radio",
        "melhores narracoes de gol futebol",
    ]
    vistos: set[str] = set()
    baixados = 0
    for consulta in consultas:
        for item in _yt_busca(consulta, n=8):
            if item["id"] in vistos:
                continue
            vistos.add(item["id"])
            if item["dur"] < 60 or item["dur"] > 3600:
                continue
            p = _yt_audio(item["id"], videos / f"{item['id']}.wav")
            if p.exists():
                baixados += 1
            if baixados >= 20:
                break
        if baixados >= 20:
            break
    log(f"gol_real: {baixados} videos de narracao")

    # Recorta os picos de volume (grito) em clipes de 2,4 s.
    total = 0
    for video in sorted(videos.glob("*.wav")):
        saidas = sorted(clips.glob(f"{video.stem}_*.wav"))
        if len(saidas) >= 6:
            total += len(saidas)
            continue
        x, _ = ler_audio(video)
        if len(x) < SR:
            continue
        passo = int(SR * 0.05)
        env = _envelope_rms(x, passo * 2, passo)
        if len(env) < 20:
            continue
        db = 20 * np.log10(np.maximum(env, 1e-6))
        limiar = np.percentile(db, 99.0)
        candidatos: list[tuple[float, int]] = []
        for i in np.argsort(db)[::-1]:
            if db[i] < limiar:
                break
            if i < 25 or i > len(env) - 25:
                continue
            if all(abs(i - j) > 40 for _, j in candidatos):
                candidatos.append((float(db[i]), int(i)))
            if len(candidatos) >= 6:
                break
        for n, (_, centro) in enumerate(candidatos):
            inicio = max(0, int(centro * 0.05 * SR) - int(0.8 * SR))
            fim = min(len(x), inicio + int(2.4 * SR))
            trecho = x[inicio:fim]
            if len(trecho) < int(1.5 * SR):
                continue
            pico = float(np.max(np.abs(trecho)))
            if pico < 0.05:
                continue
            salvar_wav16(clips / f"{video.stem}_{n:02d}.wav", trecho / max(pico, 1e-6) * 0.9)
            total += 1
    n_clips = len(list(clips.glob("*.wav")))
    log(f"gol_real: {n_clips} clipes <= 3 s em {clips}")
    if n_clips < 60:
        raise SystemExit(f"gol_real: so {n_clips} clipes (precisa >= 60)")
    registrar("Narracoes de gol recortadas (clipes <= 3 s)", "varios (ver videos/*.wav em fontes.jsonl)",
              clips, "conteudo de terceiros, uso local de avaliacao; nunca no git")


ETAPAS = {
    "openwakeword": etapa_openwakeword,
    "piper": etapa_piper,
    "rir": etapa_rir,
    "noise": etapa_noise,
    "music": etapa_music,
    "speech": etapa_speech,
    "game": etapa_game,
    "gol_real": etapa_gol_real,
}
ORDEM = ["openwakeword", "piper", "rir", "noise", "music", "speech", "game", "gol_real"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etapa", default="all", choices=["all", *ETAPAS])
    args = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    etapas = ORDEM if args.etapa == "all" else [args.etapa]
    for nome in etapas:
        log("#" * 30 + f" {nome} " + "#" * 30)
        ETAPAS[nome]()
        escrever_fontes()
    escrever_fontes()
    log("fontes em " + str(ROOT / "FONTES.md"))


if __name__ == "__main__":
    main()
