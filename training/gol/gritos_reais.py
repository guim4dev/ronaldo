#!/usr/bin/env python3
"""Gritos humanos REAIS de gol: download, recorte verificado, split e features.

Etapas (todas idempotentes):
  --baixar    busca e baixa videos publicos (torcedor, gamer, narrador) e as
              legendas automaticas do YouTube; reaproveita os 24 videos de
              narracao que ja estao em raw/gol_real/videos.
  --recortar  candidatos por legenda ("gol") e por pico de RMS; cada candidato
              e verificado com faster-whisper (language=pt, word timestamps).
              So fica o clipe cuja transcricao contem gol/goo+l/golaco. O
              recorte e justo em volta da palavra (<= 3 s, 0,3 s de folga).
  --split     divide POR VIDEO (70/30, estratificado por tipo). Nenhum video
              aparece nos dois lados. Os 125 clipes antigos de gol_real entram
              pela mesma regra, pelo video de origem.
  --features  treino -> janela de 2 s com fundo (contrato do features.py) e
              audio cru em work/real_train/; teste -> work/real_test/ +
              features/real_test.npy. Atualiza MANIFESTO.json, DADOS.md e
              FONTES.md.

Nada de audio no git: tudo vive em ~/data/gol/ (ou $GOL_DATA).

Uso:
  uv run python gritos_reais.py --baixar --alvo 200
  uv run python gritos_reais.py --recortar --workers 6
  uv run python gritos_reais.py --split
  uv run python gritos_reais.py --features --workers 6
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

import comum as C

SR = C.SR
RAW = C.RAW / "gritos"
VIDEOS = RAW / "videos"
LEGENDAS = RAW / "legendas"
CAND = RAW / "candidatos"
CLIPS = RAW / "clips"
META = RAW / "meta.jsonl"
META_FILTRADO = RAW / "meta_filtrado.jsonl"
CAND_JSONL = RAW / "candidatos.jsonl"
VIDEOS_JSON = RAW / "videos.json"
SPLIT_JSON = C.FEATURES / "real_split.json"
SPLIT_RAW = RAW / "split.json"

# "gol", "gool", "gooool", "golll"; "golaco"/"golaco!" com cedilha ou c.
RE_GOL = re.compile(r"^g[o]+l+$|^g[o]+l+a[cç]o+$", re.I)
RE_GOL_TEXTO = re.compile(r"\bgo{1,}l{1,}\b|\bgo{1,}l+a[cç]o", re.I)

TIPOS = ("torcedor", "gamer", "narrador")

CONSULTAS: dict[str, list[str]] = {
    "torcedor": [
        "torcedor comemorando gol em casa",
        "reacao da torcida no gol",
        "torcida gritando gol brasil",
        "comemoracao de gol torcedor",
        "react gol brasil torcedor",
        "torcedor gritando gol no bar",
        "reacao gol selecao brasileira",
        "festa da torcida gol",
        "torcedor surtando com gol",
        "gol do brasil reacao torcida",
        "reaccion gol torcida",
        "reaccion gol streamer",
        "gol reaccion hinchada",
        "torcida comemorando gol ao vivo",
        "bar comemorando gol",
        "vizinhos comemorando gol",
    ],
    "gamer": [
        "gamer gritando gol fifa",
        "ea fc gol gritando",
        "fifa 23 gol reacao",
        "rematch gol gritando",
        "gamer comemorando gol videogame",
        "reacao gol fifa",
        "gritando gol no fifa",
        "ea fc 24 gol reacao gamer",
        "fifa gol comemoracao",
        "gol no videogame reacao",
        "streamer gritando gol fifa",
        "gamer surtando com gol",
        "reaccion gol fifa",
        "gritando gol fc 25",
        "gol fifa reaccion streamer",
        "comemorando gol no videogame",
    ],
    "narrador": [
        "narracao de gol brasileiro",
        "narrador gritando gol",
        "gol narracao emocionante brasileiro",
        "melhores narracoes de gol",
        "galvao bueno gol narracao",
        "narracao gol radio brasileiro",
        "compilado de gols narrados",
        "melhores narracoes de gol do futebol",
        "gols historicos com narracao",
        "gols do flamengo narracao",
        "gols do corinthians narracao",
        "gols do palmeiras narracao",
        "gols da selecao brasileira narracao",
        "gols do sao paulo narracao",
        "gols do gremio narracao",
        "gols do internacional narracao",
        "gols do cruzeiro narracao",
        "gols do vasco narracao",
        "gols do botafogo narracao",
        "gols do santos narracao",
        "narracao de gol de radio",
        "gol narrado ao vivo",
        "compilado narracao esportiva",
        "gols com narracao de arrepiar",
        "melhores momentos narracao gol",
        "narracoes antigas de gol",
        "silvio luiz gol narracao",
        "luciano do valle gol narracao",
        "jose carlos araujo gol narracao",
        "narracao gol libertadores",
        "gols do flamengo compilado",
        "gols do corinthians compilado",
        "gols do palmeiras compilado",
        "gols do sao paulo compilado",
        "gols do gremio compilado",
        "gols do internacional compilado",
        "gols do cruzeiro compilado",
        "gols do vasco compilado",
        "gols do botafogo compilado",
        "gols do santos compilado",
        "gols do fluminense compilado",
        "gols do atletico mineiro compilado",
        "gols do bahia compilado",
        "gols do sport compilado",
        "gols do fortaleza compilado",
        "gols do ceara compilado",
        "gols da copa 2022 narracao",
        "gols da copa 2018 narracao",
        "gols da copa 2014 narracao",
        "gols do brasileirao narracao",
        "melhores gols da historia narracao",
        "gols de falta narracao",
        "gols de bicicleta narracao",
        "gols de cabeca narracao",
        "gols nos acrescimos narracao",
        "virada historica narracao gol",
        "final de campeonato narracao gol",
        "gol do titulo narracao",
        "gols com narracao do galvao bueno",
        "gols com narracao do silvio luiz",
        "gols com narracao do luciano do valle",
        "gols com narracao do jose carlos araujo",
        "gols com narracao do milton leite",
        "gols com narracao do osmar santos",
        "gols com narracao do cleber machado",
        "gols com narracao do luiz roberto",
        "gols com narracao do gustavo villani",
        "gols com narracao do everaldo marques",
        "gols com narracao do paulo andrade",
        "gols com narracao do rogerio vaughan",
        "narracao de gol do radio brasileiro",
        "gols com narracao de arrepiar compilado",
        "melhores narracoes do futebol brasileiro",
        "compilado de gols com narracao",
    ],
}


CONSULTAS_EXTRA: dict[str, list[str]] = {
    "torcedor": [
        "compilado reacao gol",
        "compilado de comemoracoes de gol",
        "torcedores comemorando gol compilado",
        "reacao gol brasileirao",
        "reacao gol libertadores",
        "reacao gol copa do mundo",
        "comemoracao gol selecao compilado",
        "react gol flamengo",
        "react gol corinthians",
        "react gol palmeiras",
        "reaccion al gol",
        "reaccion gol argentina",
        "reaccion gol river",
        "reaccion gol boca",
        "gritando gol reaccion",
        "reaccion gol espana",
        "reaccion gol mexico",
        "reaccion gol colombia",
        "hincha gritando gol",
        "reaccion gol liga mx",
        "reaccion gol champions",
        "gol reaccion streamer espanol",
        "reaccion gol mundial",
    ],
    "gamer": [
        "fifa gol reaction compilation",
        "ea fc goal reaction",
        "rematch goal reaction",
        "gol fifa compilation reaction",
        "gamer goal scream compilation",
        "fifa rage goal scream",
        "fc 25 gol reaction",
        "efootball gol reaction",
        "reaccion gol efootball",
        "gol en fifa reaccion",
    ],
    "narrador": [
        "gols do neymar narracao",
        "gols do messi narracao",
        "gols do cristiano ronaldo narracao",
        "gols de pele narracao",
        "gols do romario narracao",
        "gols do ronaldo fenomeno narracao",
        "gols do zico narracao",
        "gols da selecao 2002 narracao",
        "gols da selecao 1994 narracao",
        "gols da selecao 1970 narracao",
        "gols historicos do futebol brasileiro",
        "gols do brasileirao 2023 narracao",
        "gols do brasileirao 2025 narracao",
        "gols da libertadores narracao",
        "gols da champions narracao",
        "gols da copa do mundo narracao",
        "gols de falta do brasileirao narracao",
        "gols de penalti narracao",
        "gols contra narracao",
        "gols de voleio narracao",
        "gols nos ultimos minutos narracao",
        "gols aos 90 minutos narracao",
        "narracao gol do flamengo 2019",
        "narracao gol do corinthians 2012",
        "narracao gol do palmeiras 2021",
        "narracao gol do gremio 2017",
        "narracao gol do internacional 2006",
        "narracao gol do sao paulo 2005",
        "narracao gol do santos 2011",
        "narracao gol do vasco 2000",
        "narracao gol do cruzeiro 2003",
        "narracao gol do botafogo 2024",
    ],
}
for _tipo, _consultas in CONSULTAS_EXTRA.items():
    CONSULTAS.setdefault(_tipo, []).extend(_consultas)

TITULO_BOM = re.compile(
    r"gol|gool|gola[cç]o|comemora|reac|react|torcida|narra|fifa|ea fc|rematch|"
    r"sele[cç][aã]o|brasil|copa|futebol",
    re.I,
)
TITULO_RUIM = re.compile(
    r"ao vivo|full match|jogo completo|podcast|entrevista|trailer|review|"
    r"tutorial|como fazer|receita|cooking|gameplay completo|walkthrough",
    re.I,
)
TITULO_FORTE = re.compile(
    r"gol|gool|gola[cç]o|comemora|reac|react|narra|torcida", re.I
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _ytdlp() -> str:
    candidato = Path(sys.executable).parent / "yt-dlp"
    if candidato.exists():
        return str(candidato)
    achado = shutil.which("yt-dlp")
    if achado:
        return achado
    raise SystemExit("yt-dlp nao encontrado (uv add yt-dlp)")


def _url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


def _salvar_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def _ler_json(p: Path, padrao):
    if not p.exists():
        return padrao
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return padrao


# --------------------------------------------------------------------------- #
# legendas do YouTube (fonte dos candidatos precisos)
# --------------------------------------------------------------------------- #
def _baixar_legenda(vid: str, tentativas: int = 1) -> Path | None:
    LEGENDAS.mkdir(parents=True, exist_ok=True)
    alvo = LEGENDAS / f"{vid}.vtt"
    if alvo.exists() and alvo.stat().st_size > 20:
        return alvo
    # um idioma por vez: pedir pt+pt-orig+pt-BR de uma vez dispara 429.
    # Em 429 nao insiste: o caller registra legenda=False e tenta de novo
    # numa passada seguinte (o YouTube limita por IP/minuto).
    for idioma in ("pt-orig", "pt", "es"):
        cmd = [
            _ytdlp(), "--no-warnings", "--skip-download", "--write-auto-sub",
            "--sub-lang", idioma, "--sub-format", "vtt",
            "-o", str(LEGENDAS / vid), _url(vid),
        ]
        for _ in range(tentativas):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                break
            achados = sorted(LEGENDAS.glob(f"{vid}.*.vtt"))
            if achados:
                achados[0].replace(alvo)
                for extra in LEGENDAS.glob(f"{vid}.*.vtt"):
                    extra.unlink(missing_ok=True)
                _LEGENDA_429["n"] = 0
                return alvo
            erro = r.stderr or ""
            if "429" in erro or "Too Many Requests" in erro:
                _LEGENDA_429["n"] += 1
                return None
            break  # idioma sem legenda; tenta o proximo
    return None


def ler_legenda(path: Path) -> list[dict]:
    """Devolve [{t, palavra}] com os tempos das palavras (tags inline do VTT)."""
    texto = path.read_text(encoding="utf-8", errors="ignore")
    eventos: list[dict] = []
    for m in re.finditer(r"<(\d+):(\d\d):(\d\d)\.(\d+)><c>\s*([^<]*)</c>", texto):
        h, mi, s, ms, palavra = m.groups()
        t = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0
        palavra = palavra.strip()
        if palavra:
            eventos.append({"t": round(t, 3), "palavra": palavra})
    if eventos:
        eventos.sort(key=lambda e: e["t"])
        limpos: list[dict] = []
        for e in eventos:
            if limpos and abs(e["t"] - limpos[-1]["t"]) < 0.12 and e["palavra"] == limpos[-1]["palavra"]:
                continue
            limpos.append(e)
        return limpos
    # fallback: cues sem tags inline (legenda manual) — tempo proporcional
    for bloco in re.split(r"\n\s*\n", texto):
        m = re.search(
            r"(\d\d):(\d\d):(\d\d)\.(\d+) --> (\d\d):(\d\d):(\d\d)\.(\d+)", bloco
        )
        if not m:
            continue
        h0, m0, s0, ms0, h1, m1, s1, ms1 = m.groups()
        t0 = int(h0) * 3600 + int(m0) * 60 + int(s0) + int(ms0.ljust(3, "0")[:3]) / 1000.0
        t1 = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1.ljust(3, "0")[:3]) / 1000.0
        linhas = [
            l for l in bloco.splitlines()
            if l.strip() and "-->" not in l and not l.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
        ]
        palavras = " ".join(linhas).split()
        if not palavras:
            continue
        passo = max(0.05, (t1 - t0) / len(palavras))
        for i, p in enumerate(palavras):
            eventos.append({"t": round(t0 + i * passo, 3), "palavra": p})
    eventos.sort(key=lambda e: e["t"])
    return eventos


def _tok(palavra: str) -> str:
    return re.sub(r"[^0-9a-zA-ZÀ-ÿçÇ]", "", palavra).lower()


def _e_gol(palavra: str) -> bool:
    return bool(RE_GOL.fullmatch(_tok(palavra)))


def _texto_tem_gol(texto: str) -> bool:
    for p in texto.split():
        if _e_gol(p):
            return True
    return bool(RE_GOL_TEXTO.search(texto))


# --------------------------------------------------------------------------- #
# audio
# --------------------------------------------------------------------------- #
def _envelope_db(x: np.ndarray, passo_s: float = 0.05, janela_s: float = 0.10) -> np.ndarray:
    passo = max(1, int(passo_s * SR))
    janela = max(passo, int(janela_s * SR))
    k = 1 + (len(x) - janela) // passo if len(x) >= janela else 0
    if k <= 0:
        return np.zeros(0, dtype=np.float32)
    blocos = x[: k * passo].reshape(k, passo)
    env = np.sqrt((blocos.astype(np.float64) ** 2).mean(axis=1))
    return (20 * np.log10(np.maximum(env, 1e-6))).astype(np.float32)


def _db_local(db: np.ndarray, t: float, raio: float = 0.8) -> float:
    if len(db) == 0:
        return -120.0
    a = max(0, int((t - raio) / 0.05))
    b = min(len(db), int((t + raio) / 0.05) + 1)
    if b <= a:
        return -120.0
    return float(np.max(db[a:b]))


def _picos_rms(x: np.ndarray, n: int = 10) -> list[tuple[float, float]]:
    db = _envelope_db(x)
    if len(db) < 20:
        return []
    limiar = float(np.percentile(db, 99.0))
    picos: list[tuple[float, float]] = []
    for i in np.argsort(db)[::-1]:
        if float(db[i]) < limiar:
            break
        t = float(i) * 0.05
        if all(abs(t - p) > 3.0 for p, _ in picos):
            picos.append((t, float(db[i])))
        if len(picos) >= n:
            break
    return picos


def _ler(p: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    x, sr = sf.read(str(p), dtype="float32", always_2d=True)
    return x.mean(axis=1), int(sr)


def _duracao(p: Path) -> float:
    import soundfile as sf

    try:
        info = sf.info(str(p))
        return float(info.frames) / float(info.samplerate)
    except Exception:  # noqa: BLE001
        return 0.0


# --------------------------------------------------------------------------- #
# etapa 1: download
# --------------------------------------------------------------------------- #
def _busca(consulta: str, n: int = 10) -> list[dict]:
    cmd = [
        _ytdlp(), "--no-warnings", "--flat-playlist",
        "--print", "%(id)s\t%(duration)s\t%(title)s\t%(channel)s",
        f"ytsearch{n}:{consulta}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return []
    itens = []
    for linha in r.stdout.splitlines():
        partes = linha.split("\t")
        if len(partes) < 3:
            continue
        try:
            dur = float(partes[1])
        except ValueError:
            dur = 0.0
        itens.append({
            "id": partes[0],
            "dur": dur,
            "titulo": partes[2],
            "canal": partes[3] if len(partes) > 3 else "",
        })
    return itens


def _baixar_audio(vid: str, destino: Path) -> bool:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.stat().st_size > 1000:
        return True
    for fmt in ("18", "bestaudio/best"):
        cmd = [
            _ytdlp(), "--no-warnings", "--no-playlist",
            "--extractor-args", "youtube:player_client=android",
            "-f", fmt, "-x", "--audio-format", "wav",
            "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1 -sample_fmt s16",
            "-o", str(destino.with_suffix(".%(ext)s")), _url(vid),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            continue
        if destino.exists() and destino.stat().st_size > 1000:
            return True
        if r.returncode != 0:
            ultima = (r.stderr or "").strip().splitlines()
            log(f"  yt-dlp {vid} ({fmt}) falhou: {ultima[-1] if ultima else ''}")
    return False


def etapa_baixar(alvo: int, limite_busca: int, workers: int,
                 tipos: tuple[str, ...] = TIPOS, com_legendas: bool = False) -> None:
    """Baixa >= alvo videos novos, diversos, com legenda/audio 16 kHz mono."""
    VIDEOS.mkdir(parents=True, exist_ok=True)
    LEGENDAS.mkdir(parents=True, exist_ok=True)
    registro = _ler_json(VIDEOS_JSON, [])
    por_id = {v["id"]: v for v in registro}

    # os 24 videos de narracao ja baixados pela etapa gol_real entram como narrador
    antigos = C.RAW / "gol_real" / "videos"
    for p in sorted(antigos.glob("*.wav")):
        vid = p.stem
        if vid not in por_id:
            por_id[vid] = {
                "id": vid, "tipo": "narrador", "novo": False, "titulo": "",
                "dur": round(_duracao(p), 1), "canal": "", "consulta": "gol_real",
                "url": _url(vid), "caminho": str(p), "manter": True, "legenda": False,
            }

    # legendas dos videos que ja estao no registro (os 24 de narracao inclusive)
    for v in (por_id.values() if com_legendas else []):
        if v.get("legenda") is True:
            continue
        p = _baixar_legenda(v["id"])
        v["legenda"] = p is not None
        if p is not None:
            eventos = ler_legenda(p)
            v["gols_legenda"] = sum(1 for e in eventos if _e_gol(e["palavra"]))
        elif _LEGENDA_429["n"] >= 5:
            log("baixar: muitos 429 de legenda; paro esta passada")
            break
        time.sleep(1.5)
    _salvar_json(VIDEOS_JSON, sorted(por_id.values(), key=lambda v: (v["tipo"], v["id"])))

    # busca
    candidatos: list[dict] = []
    vistos: set[str] = set()
    for tipo, consultas in CONSULTAS.items():
        if tipo not in tipos:
            continue
        for consulta in consultas:
            for item in _busca(consulta, limite_busca):
                vid = item["id"]
                if vid in vistos or vid in por_id:
                    continue
                vistos.add(vid)
                limite = 1800 if tipo == "narrador" else 600
                if item["dur"] < 10 or item["dur"] > limite:
                    continue
                if TITULO_RUIM.search(item["titulo"]):
                    continue
                if not TITULO_BOM.search(item["titulo"]):
                    continue
                if tipo in ("narrador", "torcedor") and not TITULO_FORTE.search(item["titulo"]):
                    continue
                candidatos.append({**item, "tipo": tipo, "consulta": consulta})
    log(f"baixar: {len(candidatos)} candidatos de busca (alvo {alvo} novos)")

    # legendas primeiro (barato; evita baixar video sem gol). Sequencial para
    # nao disparar 429 do YouTube.
    for item in (candidatos if com_legendas else []):
        vid = item["id"]
        if por_id.get(vid, {}).get("legenda") is True:
            item["legenda"] = True
            continue
        p = _baixar_legenda(vid)
        item["legenda"] = p is not None
        if p is not None:
            eventos = ler_legenda(p)
            item["gols_legenda"] = sum(1 for e in eventos if _e_gol(e["palavra"]))
        else:
            item["gols_legenda"] = None
            if _LEGENDA_429["n"] >= 5:
                log("baixar: muitos 429 de legenda; paro esta passada")
                for resto in candidatos[candidatos.index(item) + 1:]:
                    resto["legenda"] = None
                    resto["gols_legenda"] = None
                break
        time.sleep(1.2)

    # diversidade: no maximo 8 videos por canal
    por_canal: dict[str, int] = {}
    diversos: list[dict] = []
    for item in candidatos:
        canal = item.get("canal", "")
        if canal and por_canal.get(canal, 0) >= 8:
            continue
        por_canal[canal] = por_canal.get(canal, 0) + 1
        diversos.append(item)
    candidatos = diversos

    selecionados = []
    ignorados = 0
    for item in candidatos:
        if com_legendas:
            tem_legenda = item.get("legenda")
            gols = item.get("gols_legenda")
            if tem_legenda and gols == 0 and not TITULO_FORTE.search(item["titulo"]):
                ignorados += 1
                continue
        selecionados.append(item)
    log(f"baixar: {len(selecionados)} selecionados ({ignorados} sem gol na legenda)")

    # download paralelo
    baixados_novos = sum(1 for v in por_id.values() if v.get("novo"))
    fila = [i for i in selecionados if i["id"] not in por_id]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {}
        while fila and baixados_novos < alvo:
            while fila and len(futuros) < workers:
                item = fila.pop(0)
                destino = VIDEOS / f"{item['id']}.wav"
                futuros[pool.submit(_baixar_audio, item["id"], destino)] = item
            if not futuros:
                break
            for f in as_completed(list(futuros)):
                item = futuros.pop(f)
                try:
                    ok = f.result()
                except Exception as exc:  # noqa: BLE001
                    log(f"  download {item['id']} erro: {exc}")
                    ok = False
                if ok:
                    destino = VIDEOS / f"{item['id']}.wav"
                    dur = _duracao(destino)
                    por_id[item["id"]] = {
                        "id": item["id"], "tipo": item["tipo"], "novo": True,
                        "titulo": item["titulo"], "dur": round(dur, 1),
                        "canal": item.get("canal", ""), "consulta": item["consulta"],
                        "url": _url(item["id"]), "caminho": str(destino),
                        "manter": False, "legenda": bool(item.get("legenda")),
                        "gols_legenda": item.get("gols_legenda"),
                    }
                    baixados_novos += 1
                    log(f"  baixado {item['id']} [{item['tipo']}] {dur:.0f}s ({baixados_novos}/{alvo})")
                    _salvar_json(VIDEOS_JSON, sorted(por_id.values(), key=lambda v: (v["tipo"], v["id"])))
                if baixados_novos >= alvo:
                    for outro in futuros:
                        outro.cancel()
                    break
            if baixados_novos >= alvo:
                break

    _salvar_json(VIDEOS_JSON, sorted(por_id.values(), key=lambda v: (v["tipo"], v["id"])))
    novos = [v for v in por_id.values() if v.get("novo")]
    log(f"baixar: {len(novos)} videos novos, {len(por_id)} no total")
    for tipo in TIPOS:
        n = sum(1 for v in por_id.values() if v["tipo"] == tipo)
        nn = sum(1 for v in novos if v["tipo"] == tipo)
        log(f"  {tipo}: {n} videos ({nn} novos)")


# --------------------------------------------------------------------------- #
# etapa 2: candidatos + verificacao com faster-whisper
# --------------------------------------------------------------------------- #
_MODELO = None
_LEGENDA_429 = {"n": 0}


def _modelo():
    global _MODELO
    if _MODELO is None:
        from faster_whisper import WhisperModel

        _MODELO = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=2)
    return _MODELO


def _transcrever(x: np.ndarray) -> dict:
    m = _modelo()
    segmentos, _ = m.transcribe(
        x, language="pt", beam_size=1, word_timestamps=True,
        vad_filter=False, temperature=0, condition_on_previous_text=False,
    )
    texto: list[str] = []
    palavras: list[tuple[float, float, str]] = []
    segs: list[tuple[float, float, str]] = []
    for s in segmentos:
        texto.append(s.text)
        segs.append((float(s.start), float(s.end), s.text))
        for w in (s.words or []):
            palavras.append((float(w.start), float(w.end), w.word))
    return {"texto": " ".join(texto).strip(), "palavras": palavras, "segmentos": segs}


def _verificar(cand: dict) -> dict:
    """Roda whisper no candidato e grava o clipe justo se a transcricao tem gol."""
    import soundfile as sf

    x, sr = _ler(Path(cand["arquivo"]))
    if len(x) < int(0.2 * SR):
        return {**cand, "ok": False, "motivo": "curto"}
    tr = _transcrever(x)
    alvo = float(cand["alvo"])
    duracao = len(x) / sr
    gol_palavras = [w for w in tr["palavras"] if _e_gol(w[2])]
    gol_segs = [s for s in tr["segmentos"] if _texto_tem_gol(s[2])]

    inicio_rel = fim_rel = None
    fonte = None
    detalhe = None
    if gol_palavras:
        w = min(gol_palavras, key=lambda w: abs((w[0] + w[1]) / 2 - alvo))
        inicio_rel, fim_rel = w[0] - 0.3, w[1] + 0.3
        fonte = "whisper"
        detalhe = w[2].strip()
    elif gol_segs:
        s = min(gol_segs, key=lambda s: abs((s[0] + s[1]) / 2 - alvo))
        inicio_rel, fim_rel = s[0] - 0.3, s[1] + 0.3
        fonte = "whisper_segmento"
        detalhe = s[2].strip()
    elif cand["fonte"] == "legenda":
        prox = float(cand.get("proximo", alvo + 1.2))
        inicio_rel = alvo - 0.3
        fim_rel = min(alvo + 2.7, prox if prox > alvo + 0.4 else alvo + 1.2)
        fonte = "youtube"
        detalhe = cand.get("texto_legenda", "gol")
    else:
        return {**cand, "ok": False, "motivo": "sem gol", "texto_whisper": tr["texto"]}

    # <= 3 s, centrado na palavra quando ela e longa
    if fim_rel - inicio_rel > 3.0:
        meio = (inicio_rel + fim_rel) / 2
        inicio_rel, fim_rel = meio - 1.5, meio + 1.5
    inicio_rel = max(0.0, inicio_rel)
    fim_rel = min(duracao, fim_rel)
    if fim_rel - inicio_rel < 0.3:
        return {**cand, "ok": False, "motivo": "recorte curto", "texto_whisper": tr["texto"]}

    trecho = x[int(inicio_rel * sr): int(fim_rel * sr)].copy()
    pico = float(np.max(np.abs(trecho))) if len(trecho) else 0.0
    if pico > 0.99:
        trecho = trecho / pico * 0.99
    destino = CLIPS / f"{cand['video']}_{cand['i']:02d}.wav"
    C.salvar_wav16(destino, trecho)

    texto = detalhe if fonte == "youtube" else tr["texto"]
    return {
        **cand,
        "ok": True,
        "clipe": destino.name,
        "inicio_abs": round(float(cand["inicio"]) + inicio_rel, 3),
        "fim_abs": round(float(cand["inicio"]) + fim_rel, 3),
        "duracao": round(float(fim_rel - inicio_rel), 3),
        "fonte_transcricao": fonte,
        "texto": texto,
        "texto_whisper": tr["texto"],
        "palavra": detalhe,
    }


def _candidatos_do_video(video: dict, x: np.ndarray) -> list[dict]:
    """Legendas (precisas) + picos de RMS (fallback), sem sobreposicao."""
    dur = len(x) / SR
    db = _envelope_db(x)
    limiar_legenda = float(np.percentile(db, 60)) if len(db) else -120.0
    cands: list[dict] = []
    vid = video["id"]
    max_legenda = 16 if video["tipo"] == "narrador" else 10
    max_total = 18 if video["tipo"] == "narrador" else 10

    eventos: list[dict] = []
    legenda = LEGENDAS / f"{vid}.vtt"
    if legenda.exists():
        eventos = [e for e in ler_legenda(legenda) if _e_gol(e["palavra"])]
    # um "gol" a cada 2,5 s no maximo; os mais altos primeiro
    eventos.sort(key=lambda e: e["t"])
    escolhidos: list[dict] = []
    for e in eventos:
        if any(abs(e["t"] - o["t"]) < 2.5 for o in escolhidos):
            continue
        if _db_local(db, e["t"]) < limiar_legenda:
            continue
        escolhidos.append(e)
    escolhidos.sort(key=lambda e: _db_local(db, e["t"]), reverse=True)
    escolhidos = escolhidos[:max_legenda]
    escolhidos.sort(key=lambda e: e["t"])

    for e in escolhidos:
        t = float(e["t"])
        a = max(0.0, t - 1.5)
        b = min(dur, t + 2.5)
        prox = [o["t"] for o in eventos if o["t"] > t + 0.05]
        cands.append({
            "video": vid, "tipo": video["tipo"], "i": len(cands),
            "inicio": round(a, 3), "fim": round(b, 3), "alvo": round(t - a, 3),
            "fonte": "legenda", "texto_legenda": e["palavra"],
            "proximo": round((prox[0] - a) if prox else (t - a + 1.2), 3),
            "db": round(_db_local(db, t), 1),
        })

    # picos de RMS: completa ate o teto; sem legenda, usa o teto inteiro
    alvo_rms = max_total if not escolhidos else max(0, max_total - len(cands))
    picos = _picos_rms(x, n=alvo_rms + 4)
    for t, dbp in picos:
        if len(cands) >= max_total:
            break
        if any(abs(t - (c["inicio"] + c["alvo"])) < 2.0 for c in cands):
            continue
        a = max(0.0, t - 2.5)
        b = min(dur, t + 2.5)
        cands.append({
            "video": vid, "tipo": video["tipo"], "i": len(cands),
            "inicio": round(a, 3), "fim": round(b, 3), "alvo": round(t - a, 3),
            "fonte": "rms", "texto_legenda": "", "proximo": round(t - a + 1.2, 3),
            "db": round(dbp, 1),
        })
    return cands


def _clips_da_transcricao(video: dict, x: np.ndarray, tr: dict, db: np.ndarray) -> list[dict]:
    """Clipe justo em volta de cada "gol" que a transcricao completa encontrou.

    A transcricao completa substitui o pico de RMS como localizador: o pico
    muitas vezes nao coincide com a palavra. O RMS continua como filtro de
    volume (>= percentil 60 do proprio video).
    """
    dur = len(x) / SR
    if len(db) == 0:
        return []
    piso = float(np.percentile(db, 50))
    gols: list[tuple[float, float, str, float]] = []
    for a, b, w in tr["palavras"]:
        if not _e_gol(w) or (b - a) < 0.15:
            continue
        dbl = _db_local(db, (a + b) / 2)
        if dbl < piso:
            continue
        gols.append((a, b, w, dbl))
    # prefere as ocorrencias longas (grito) e separa por 1,5 s
    gols.sort(key=lambda g: (g[1] - g[0]), reverse=True)
    escolhidos: list[tuple[float, float, str, float]] = []
    for g in gols:
        mid = (g[0] + g[1]) / 2
        if any(abs(mid - (h[0] + h[1]) / 2) < 1.2 for h in escolhidos):
            continue
        escolhidos.append(g)
        if len(escolhidos) >= 30:
            break
    escolhidos.sort(key=lambda g: g[0])

    vid = video["id"]
    clips: list[dict] = []
    for n, (a, b, w, dbl) in enumerate(escolhidos):
        inicio, fim = a - 0.3, b + 0.3
        if fim - inicio > 3.0:
            meio = (inicio + fim) / 2
            inicio, fim = meio - 1.5, meio + 1.5
        inicio, fim = max(0.0, inicio), min(dur, fim)
        if fim - inicio < 0.3:
            continue
        trecho = x[int(inicio * SR): int(fim * SR)].copy()
        pico = float(np.max(np.abs(trecho))) if len(trecho) else 0.0
        if pico > 0.99:
            trecho = trecho / pico * 0.99
        nome = f"{vid}_{n:02d}.wav"
        C.salvar_wav16(CLIPS / nome, trecho)
        clips.append({
            "video": vid, "tipo": video["tipo"], "i": n, "clipe": nome,
            "inicio_abs": round(inicio, 3), "fim_abs": round(fim, 3),
            "duracao": round(fim - inicio, 3), "fonte": "transcricao",
            "fonte_transcricao": "whisper", "texto": tr["texto"],
            "texto_whisper": tr["texto"], "palavra": w.strip(),
            "db": round(dbl, 1), "ok": True,
        })
    return clips


def _processar_video(video: dict, manter_videos: bool) -> list[dict]:
    caminho = Path(video["caminho"])
    x, sr = _ler(caminho)
    if sr != SR:
        x = C.resample(x, sr)
    db = _envelope_db(x)
    tr = _transcrever(x)
    clips = _clips_da_transcricao(video, x, tr, db)
    if not clips:
        # fallback: candidatos por legenda/RMS, verificados um a um
        for cand in _candidatos_do_video(video, x):
            a = int(cand["inicio"] * SR)
            b = int(cand["fim"] * SR)
            trecho = x[a:b]
            if len(trecho) < int(0.3 * SR):
                continue
            p = CAND / f"{video['id']}_{cand['i']:02d}.wav"
            C.salvar_wav16(p, trecho)
            cand["arquivo"] = str(p)
            r = _verificar(cand)
            if r.get("ok") and r.get("clipe"):
                clips.append(r)
    if not manter_videos and not video.get("manter"):
        caminho.unlink(missing_ok=True)
    return clips


def etapa_recortar(workers: int, manter_videos: bool, limite_videos: int = 0) -> None:
    CLIPS.mkdir(parents=True, exist_ok=True)
    CAND.mkdir(parents=True, exist_ok=True)
    videos = _ler_json(VIDEOS_JSON, [])
    if not videos:
        raise SystemExit("sem videos.json (rode --baixar)")

    feitos: dict[str, dict] = {}
    if META.exists():
        for m in _ler_jsonl(META):
            if m.get("ok") and m.get("clipe"):
                feitos[m["clipe"]] = m

    tarefas = [v for v in videos if Path(v["caminho"]).exists()]
    if limite_videos:
        tarefas = tarefas[:limite_videos]
    log(f"recortar: {len(tarefas)} videos com audio para transcrever")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(_processar_video, v, manter_videos): v for v in tarefas}
        for n, f in enumerate(as_completed(futuros), 1):
            v = futuros[f]
            try:
                clips = f.result()
            except Exception as exc:  # noqa: BLE001
                log(f"  erro em {v['id']}: {exc}")
                clips = []
            # substitui os clipes anteriores desse video (idempotente)
            for chave in [k for k, m in feitos.items() if m.get("video") == v["id"]]:
                feitos.pop(chave, None)
            for c in clips:
                feitos[c["clipe"]] = c
            log(f"  {n}/{len(futuros)} {v['id']} [{v['tipo']}]: {len(clips)} clipes ({time.time()-t0:.0f}s)")
            _salvar_jsonl(META, sorted(feitos.values(), key=lambda m: (m["video"], m["clipe"])))
    log(f"recortar: {len(feitos)} clipes em {CLIPS}")

    # os 125 clipes antigos de gol_real: mesma verificacao, mesmo video
    antigos_dir = C.RAW / "gol_real" / "clips"
    antigos = sorted(antigos_dir.glob("*.wav")) if antigos_dir.exists() else []
    if antigos:
        _verificar_antigos(antigos, feitos, workers)
        _verificar_antigos_por_legenda(feitos)



def _verificar_antigos_por_legenda(feitos: dict[str, dict]) -> None:
    """Recupera clipe antigo cujo momento tem "gol" na legenda do video.

    O clipe antigo foi cortado no pico de RMS; a legenda diz se aquele trecho
    tem a palavra gol. A posicao e achada por correlacao cruzada com o video.
    """
    from scipy.signal import fftconvolve

    antigos_dir = C.RAW / "gol_real" / "clips"
    videos_dir = C.RAW / "gol_real" / "videos"
    por_video: dict[str, list[Path]] = {}
    for p in sorted(antigos_dir.glob("*.wav")):
        if f"antigo_{p.stem}.wav" in feitos:
            continue
        vid = p.stem.rsplit("_", 1)[0]
        por_video.setdefault(vid, []).append(p)
    recuperados = 0
    for vid, clips in por_video.items():
        video = videos_dir / f"{vid}.wav"
        legenda = LEGENDAS / f"{vid}.vtt"
        if not video.exists() or not legenda.exists():
            continue
        eventos = [e for e in ler_legenda(legenda) if _e_gol(e["palavra"])]
        if not eventos:
            continue
        x, sr = _ler(video)
        if sr != SR:
            x = C.resample(x, sr)
        for p in clips:
            y, _ = _ler(p)
            n = len(y)
            if n < int(0.3 * SR) or n >= len(x):
                continue
            yc = y - y.mean()
            corr = fftconvolve(x, yc[::-1], mode="valid")
            k = int(np.argmax(corr))
            seg = x[k: k + n]
            seg = seg - seg.mean()
            den = float(np.linalg.norm(seg) * np.linalg.norm(yc))
            coef = float(np.dot(seg, yc) / den) if den > 0 else 0.0
            if coef < 0.5:
                continue
            centro = (k + n / 2) / SR
            if not any(abs(e["t"] - centro) <= 3.0 for e in eventos):
                continue
            e = min(eventos, key=lambda e: abs(e["t"] - centro))
            nome = f"antigo_{p.stem}.wav"
            C.salvar_wav16(CLIPS / nome, y)
            feitos[nome] = {
                "video": vid, "tipo": "narrador", "i": 0, "clipe": nome,
                "inicio_abs": round(k / SR, 3), "fim_abs": round((k + n) / SR, 3),
                "duracao": round(n / SR, 3), "fonte": "clipe_antigo",
                "fonte_transcricao": "youtube", "texto": e["palavra"],
                "texto_whisper": "", "palavra": e["palavra"], "db": 0.0,
                "ok": True, "correlacao": round(coef, 3),
            }
            recuperados += 1
    if recuperados:
        _salvar_jsonl(META, sorted(feitos.values(), key=lambda m: (m["video"], m["clipe"])))
        log(f"recortar: {recuperados} clipes antigos recuperados pela legenda")

def _verificar_antigos(antigos: list[Path], feitos: dict[str, dict], workers: int) -> None:
    """Verifica os clipes antigos e os inclui se a transcricao tiver gol."""
    pendentes = []
    for p in antigos:
        nome = f"antigo_{p.stem}.wav"
        if nome in feitos or (CLIPS / nome).exists():
            continue
        vid = p.stem.rsplit("_", 1)[0]
        pendentes.append({
            "video": vid, "tipo": "narrador", "i": 90 + int(p.stem.rsplit("_", 1)[-1])
            if p.stem.rsplit("_", 1)[-1].isdigit() else 90,
            "inicio": 0.0, "fim": _duracao(p), "alvo": _duracao(p) / 2,
            "fonte": "rms", "texto_legenda": "", "proximo": 1.2,
            "db": 0.0, "arquivo": str(p), "antigo": True,
        })
    if not pendentes:
        return
    log(f"recortar: {len(pendentes)} clipes antigos para verificar")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(_verificar_antigo, c): c for c in pendentes}
        for f in as_completed(futuros):
            try:
                r = f.result()
            except Exception as exc:  # noqa: BLE001
                log(f"  erro clipe antigo: {exc}")
                continue
            if r.get("ok") and r.get("clipe"):
                feitos[r["clipe"]] = r
    _salvar_jsonl(META, sorted(feitos.values(), key=lambda m: (m["video"], m["clipe"])))
    log(f"recortar: {len(feitos)} clipes no total (com antigos verificados)")


def _verificar_antigo(cand: dict) -> dict:
    import soundfile as sf

    x, sr = _ler(Path(cand["arquivo"]))
    tr = _transcrever(x)
    gols = [w for w in tr["palavras"] if _e_gol(w[2])]
    segs = [s for s in tr["segmentos"] if _texto_tem_gol(s[2])]
    if gols:
        w = min(gols, key=lambda w: abs((w[0] + w[1]) / 2 - cand["alvo"]))
        a, b = w[0] - 0.3, w[1] + 0.3
        fonte, detalhe = "whisper", w[2].strip()
    elif segs:
        s = min(segs, key=lambda s: abs((s[0] + s[1]) / 2 - cand["alvo"]))
        a, b = s[0] - 0.3, s[1] + 0.3
        fonte, detalhe = "whisper_segmento", s[2].strip()
    else:
        return {**cand, "ok": False, "motivo": "sem gol", "texto_whisper": tr["texto"]}
    dur = len(x) / sr
    if b - a > 3.0:
        meio = (a + b) / 2
        a, b = meio - 1.5, meio + 1.5
    a, b = max(0.0, a), min(dur, b)
    if b - a < 0.3:
        return {**cand, "ok": False, "motivo": "recorte curto", "texto_whisper": tr["texto"]}
    trecho = x[int(a * sr): int(b * sr)].copy()
    pico = float(np.max(np.abs(trecho))) if len(trecho) else 0.0
    if pico > 0.99:
        trecho = trecho / pico * 0.99
    nome = f"antigo_{Path(cand['arquivo']).stem}.wav"
    C.salvar_wav16(CLIPS / nome, trecho)
    return {**cand, "ok": True, "clipe": nome, "inicio_abs": round(a, 3),
            "fim_abs": round(b, 3), "duracao": round(b - a, 3),
            "fonte_transcricao": fonte, "texto": tr["texto"],
            "texto_whisper": tr["texto"], "palavra": detalhe}



# --------------------------------------------------------------------------- #
# etapa 2b: filtro final (alucinacao e volume de grito)
# --------------------------------------------------------------------------- #
def _texto_repetido(texto: str) -> bool:
    """Detecta alucinacao do whisper: n-grama repetido em sequencia."""
    tokens = re.findall(r"[0-9a-zA-ZÀ-ÿçÇ]+", (texto or "").lower())
    if len(tokens) < 4:
        return False
    for n in (1, 2, 3):
        rep = 1
        for i in range(n, len(tokens)):
            if tokens[i - n: i] == tokens[i: i + n]:
                rep += 1
                if rep >= 3:
                    return True
            else:
                rep = 1
    unicos = len(set(tokens)) / len(tokens)
    return len(tokens) >= 20 and unicos < 0.30


def _pico_rms_db(x: np.ndarray) -> float:
    db = _envelope_db(x, 0.05, 0.10)
    return float(np.max(db)) if len(db) else -120.0


def _mediana_fala(x: np.ndarray) -> float:
    db = _envelope_db(x, 0.05, 0.10)
    if len(db) == 0:
        return -120.0
    piso = float(np.percentile(db, 30))
    fala = db[db >= piso]
    return float(np.median(fala)) if len(fala) else float(np.median(db))


def _garantir_audio(video: dict) -> Path | None:
    p = Path(video["caminho"])
    if p.exists() and p.stat().st_size > 1000:
        return p
    if _baixar_audio(video["id"], p):
        return p
    return None


def _metricas_clipe(clipe: str) -> dict:
    x, sr = _ler(CLIPS / clipe)
    if sr != SR:
        x = C.resample(x, sr)
    tr = _transcrever(x)
    return {
        "texto_clipe": tr["texto"],
        "tem_gol_clipe": _texto_tem_gol(tr["texto"]),
        "repetido": _texto_repetido(tr["texto"]),
        "pico_clipe_db": round(_pico_rms_db(x), 1),
        "duracao_clipe": round(len(x) / sr, 3),
    }


def etapa_filtrar(workers: int) -> None:
    """Descarta alucinacao do whisper e clipe que nao e grito.

    Regras do cavaleiro:
    - texto do clipe repetido (ex.: "E eu? E eu?") -> descarta;
    - clipe sem gol/golaco no trecho -> descarta;
    - pico RMS do clipe < mediana da fala do video + 6 dB -> descarta.
    """
    meta = [m for m in _ler_jsonl(META) if m.get("ok") and m.get("clipe")]
    if not meta:
        raise SystemExit("sem clipes (rode --recortar)")
    videos = {v["id"]: v for v in _ler_json(VIDEOS_JSON, [])}

    # 1) garante o audio dos videos com clipe para medir a mediana da fala
    faltando = sorted({m["video"] for m in meta if not Path(videos.get(m["video"], {}).get("caminho", "")).exists()})
    if faltando:
        log(f"filtrar: rebaixando {len(faltando)} videos para medir a mediana da fala")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = {pool.submit(_garantir_audio, videos[v]): v for v in faltando if v in videos}
            for n, f in enumerate(as_completed(futuros), 1):
                if f.result() is None:
                    log(f"  audio indisponivel: {futuros[f]}")
                if n % 10 == 0:
                    log(f"  {n}/{len(futuros)} audios")

    mediana: dict[str, float] = {}
    for vid in sorted({m["video"] for m in meta}):
        p = Path(videos.get(vid, {}).get("caminho", ""))
        if p.exists():
            x, sr = _ler(p)
            if sr != SR:
                x = C.resample(x, sr)
            mediana[vid] = round(_mediana_fala(x), 1)
        else:
            mediana[vid] = -120.0

    # 2) re-transcreve cada clipe (texto local) em paralelo
    log(f"filtrar: re-transcrevendo {len(meta)} clipes")
    metricas: dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(_metricas_clipe, m["clipe"]): m for m in meta}
        for n, f in enumerate(as_completed(futuros), 1):
            try:
                metricas[futuros[f]["clipe"]] = f.result()
            except Exception as exc:  # noqa: BLE001
                log(f"  erro em {futuros[f]['clipe']}: {exc}")
            if n % 50 == 0 or n == len(futuros):
                log(f"  {n}/{len(futuros)} clipes re-transcritos")

    # 3) aplica as regras
    descartes = {"alucinacao": 0, "sem_gol_no_trecho": 0, "nao_e_grito": 0}
    por_tipo_descarte = {t: {"alucinacao": 0, "sem_gol_no_trecho": 0, "nao_e_grito": 0} for t in TIPOS}
    mantidos: list[dict] = []
    for m in meta:
        met = metricas.get(m["clipe"], {})
        m.update(met)
        m["mediana_fala_db"] = mediana.get(m["video"], -120.0)
        m["db_acima_mediana"] = round(float(m.get("pico_clipe_db", -120.0)) - m["mediana_fala_db"], 1)
        tipo = m.get("tipo", "narrador")
        if m.get("repetido"):
            descartes["alucinacao"] += 1
            por_tipo_descarte[tipo]["alucinacao"] += 1
            continue
        if not (m.get("tem_gol_clipe") or _e_gol(m.get("palavra", ""))):
            descartes["sem_gol_no_trecho"] += 1
            por_tipo_descarte[tipo]["sem_gol_no_trecho"] += 1
            continue
        if m["db_acima_mediana"] < 6.0:
            descartes["nao_e_grito"] += 1
            por_tipo_descarte[tipo]["nao_e_grito"] += 1
            continue
        mantidos.append(m)

    _salvar_jsonl(META_FILTRADO, sorted(mantidos, key=lambda m: (m["video"], m["clipe"])))
    resumo = {
        "total_antes": len(meta),
        "total_depois": len(mantidos),
        "descartes": descartes,
        "por_tipo_descarte": por_tipo_descarte,
        "por_tipo": {t: sum(1 for m in mantidos if m["tipo"] == t) for t in TIPOS},
        "videos": len({m["video"] for m in mantidos}),
    }
    _salvar_json(RAW / "filtro.json", resumo)
    log(f"filtrar: {len(mantidos)}/{len(meta)} clipes mantidos")
    log(f"  descartes: {descartes}")
    log(f"  por tipo: {resumo['por_tipo']}")


# --------------------------------------------------------------------------- #
# etapa 3: split por video
# --------------------------------------------------------------------------- #
def _ler_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for linha in p.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            try:
                out.append(json.loads(linha))
            except json.JSONDecodeError:
                pass
    return out


def _salvar_jsonl(p: Path, itens: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for it in itens:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def _dedup_antigos(clips: list[dict]) -> list[dict]:
    """Remove clipe antigo que e o mesmo audio de um clipe novo do mesmo video."""
    from scipy.signal import fftconvolve

    novos_por_video: dict[str, list[np.ndarray]] = {}
    for c in clips:
        if c.get("antigo"):
            continue
        x, _ = _ler(CLIPS / c["clipe"])
        novos_por_video.setdefault(c["video"], []).append(x)
    saida = []
    for c in clips:
        if not c.get("antigo"):
            saida.append(c)
            continue
        x, _ = _ler(CLIPS / c["clipe"])
        duplicado = False
        for y in novos_por_video.get(c["video"], []):
            n = min(len(x), len(y))
            if n < int(0.4 * SR):
                continue
            a = x[:n] - x[:n].mean()
            b = y[:n] - y[:n].mean()
            den = float(np.linalg.norm(a) * np.linalg.norm(b))
            if den <= 0:
                continue
            corr = float(np.max(fftconvolve(b, a[::-1], mode="full"))) / den
            if corr > 0.85:
                duplicado = True
                break
        if not duplicado:
            saida.append(c)
    return saida


def etapa_split(min_treino: int, min_teste: int, min_videos_teste: int) -> None:
    fonte = META_FILTRADO if META_FILTRADO.exists() else META
    meta = [m for m in _ler_jsonl(fonte) if m.get("ok") and m.get("clipe")]
    if not meta:
        raise SystemExit("sem clipes verificados (rode --recortar)")
    meta = _dedup_antigos(meta)
    # cada clipe precisa existir e ter <= 3 s
    meta = [m for m in meta if (CLIPS / m["clipe"]).exists()]
    por_video: dict[str, list[dict]] = {}
    for m in meta:
        por_video.setdefault(m["video"], []).append(m)

    rng = random.Random(7)
    videos_treino: list[str] = []
    videos_teste: list[str] = []
    for tipo in TIPOS:
        vids = sorted(v for v in por_video if por_video[v][0]["tipo"] == tipo)
        rng.shuffle(vids)
        n_teste = max(1, round(0.30 * len(vids))) if vids else 0
        videos_teste.extend(vids[:n_teste])
        videos_treino.extend(vids[n_teste:])

    def clips_de(vids: list[str]) -> list[dict]:
        return [c for v in vids for c in por_video[v]]

    # ajusta para as metas: teste >= min_teste e >= min_videos_teste;
    # treino >= min_treino. Move videos inteiros (nunca divide video).
    def mover(de: list[str], para: list[str], vid: str) -> None:
        de.remove(vid)
        para.append(vid)

    while len(videos_teste) < min_videos_teste:
        # move o maior video de treino do tipo com mais videos
        candidatos = sorted(videos_treino, key=lambda v: -len(por_video[v]))
        if not candidatos:
            break
        mover(videos_treino, videos_teste, candidatos[0])
    while len(clips_de(videos_teste)) < min_teste:
        candidatos = sorted(videos_treino, key=lambda v: -len(por_video[v]))
        if not candidatos:
            break
        mover(videos_treino, videos_teste, candidatos[0])
    while len(clips_de(videos_treino)) < min_treino:
        # devolve o menor video de teste (mantendo as metas do teste)
        candidatos = sorted(videos_teste, key=lambda v: len(por_video[v]))
        if len(videos_teste) <= min_videos_teste or len(clips_de(videos_teste)) - len(por_video[candidatos[0]]) < min_teste:
            break
        mover(videos_teste, videos_treino, candidatos[0])

    treino = sorted(clips_de(videos_treino), key=lambda c: c["clipe"])
    teste = sorted(clips_de(videos_teste), key=lambda c: c["clipe"])
    if len(treino) < min_treino or len(teste) < min_teste or len(videos_teste) < min_videos_teste:
        raise SystemExit(
            f"split insuficiente: treino {len(treino)} (min {min_treino}), "
            f"teste {len(teste)} (min {min_teste}), videos de teste {len(videos_teste)} "
            f"(min {min_videos_teste}). Baixe mais videos."
        )

    def contar(clips: list[dict]) -> dict[str, int]:
        out = {t: 0 for t in TIPOS}
        for c in clips:
            out[c["tipo"]] = out.get(c["tipo"], 0) + 1
        return out

    split = {
        "regra": "split por video: nenhum video aparece nos dois lados; 70/30 estratificado por tipo",
        "seed": 7,
        "treino": [c["clipe"] for c in treino],
        "teste": [c["clipe"] for c in teste],
        "videos_treino": sorted(videos_treino),
        "videos_teste": sorted(videos_teste),
        "por_tipo_treino": contar(treino),
        "por_tipo_teste": contar(teste),
        "contagens": {
            "clipes_treino": len(treino),
            "clipes_teste": len(teste),
            "videos_treino": len(videos_treino),
            "videos_teste": len(videos_teste),
        },
    }
    _salvar_json(SPLIT_JSON, split)
    _salvar_json(SPLIT_RAW, split)
    log(f"split: treino {len(treino)} clipes / {len(videos_treino)} videos; "
        f"teste {len(teste)} clipes / {len(videos_teste)} videos")
    log(f"  por tipo treino: {split['por_tipo_treino']}")
    log(f"  por tipo teste: {split['por_tipo_teste']}")


# --------------------------------------------------------------------------- #
# etapa 4: features
# --------------------------------------------------------------------------- #
def _features_worker(args: tuple[str, str]) -> tuple[str, np.ndarray]:
    caminho, saida = args
    import features as F

    x, sr = _ler(Path(caminho))
    if sr != SR:
        x = C.resample(x, sr)
    feats = F.features_clip(x)
    return saida, feats.astype(np.float16)


def _janela_2s(x: np.ndarray, seed: str) -> np.ndarray:
    """Clipe no FIM de uma janela de 2 s, com fundo (contrato do features.py)."""
    rng = random.Random(seed)
    fundo = C.fundo_aleatorio(rng, [("game", 0.45), ("noise", 0.25), ("music", 0.20)], 3.0)
    clip = x[-C.JANELA:] if len(x) > C.JANELA else x
    return C.janela_com_fundo(clip, fundo, rng)


def etapa_features(workers: int) -> None:
    split = _ler_json(SPLIT_JSON, None)
    if not split:
        raise SystemExit("sem real_split.json (rode --split)")
    fonte = META_FILTRADO if META_FILTRADO.exists() else META
    meta = {m["clipe"]: m for m in _ler_jsonl(fonte) if m.get("ok")}
    saidas = {}
    for lado, pasta in (("treino", C.WORK / "real_train"), ("teste", C.WORK / "real_test")):
        pasta.mkdir(parents=True, exist_ok=True)
        janelas: list[tuple[str, str]] = []
        for nome in split[lado]:
            origem = CLIPS / nome
            if not origem.exists():
                continue
            x, sr = _ler(origem)
            if sr != SR:
                x = C.resample(x, sr)
            # audio cru 16 kHz para o soldado de modelo gerar janelas deslocadas
            C.salvar_wav16(pasta / nome, x)
            janelas.append((str(pasta / nome), nome))
        saidas[lado] = janelas
        log(f"features: {lado}: {len(janelas)} clipes crus em {pasta}")

    FEAT = C.FEATURES
    FEAT.mkdir(parents=True, exist_ok=True)
    for lado, nome_npy in (("treino", "real_train.npy"), ("teste", "real_test.npy")):
        janelas = saidas[lado]
        pedidos = []
        for caminho, nome in janelas:
            x, sr = _ler(Path(caminho))
            if sr != SR:
                x = C.resample(x, sr)
            janela = _janela_2s(x, f"real:{lado}:{nome}")
            tmp = C.WORK / f"_real_janela_{lado}" / nome
            C.salvar_wav16(tmp, janela)
            pedidos.append((str(tmp), nome))
        arrs: list[np.ndarray] = []
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for n, (nome, arr) in enumerate(pool.map(_features_worker, pedidos), 1):
                arrs.append(arr)
                if n % 100 == 0:
                    log(f"  {lado}: {n}/{len(pedidos)} janelas")
        arr = np.stack(arrs).astype(np.float16) if arrs else np.zeros((0, 16, 96), np.float16)
        np.save(FEAT / nome_npy, arr)
        log(f"features: {nome_npy}: {arr.shape} {arr.dtype}")
        shutil.rmtree(C.WORK / f"_real_janela_{lado}", ignore_errors=True)

    # metadados por tipo e videos
    def resumo(lado: str) -> dict:
        nomes = split[lado]
        por_tipo = {t: 0 for t in TIPOS}
        for nome in nomes:
            m = meta.get(nome)
            if m:
                por_tipo[m["tipo"]] = por_tipo.get(m["tipo"], 0) + 1
        return {
            "clipes": len(nomes),
            "videos": len(split[f"videos_{lado}"]),
            "por_tipo": por_tipo,
        }

    info = {
        "real_train": {"arquivo": "features/real_train.npy", **resumo("treino")},
        "real_test": {"arquivo": "features/real_test.npy", **resumo("teste")},
        "split": str(SPLIT_JSON.relative_to(C.ROOT)),
        "clipes_crus": {"treino": str(C.WORK / "real_train"), "teste": str(C.WORK / "real_test")},
    }
    _salvar_json(RAW / "features_meta.json", info)
    _atualizar_manifesto(info)
    _atualizar_fontes()
    log("features: pronto")


def _atualizar_manifesto(info: dict) -> None:
    p = C.ROOT / "MANIFESTO.json"
    if not p.exists():
        log("manifesto: MANIFESTO.json ausente; pulo (rode manifesto.py)")
        return
    m = json.loads(p.read_text(encoding="utf-8"))
    m["arquivos"] = [a for a in m["arquivos"] if a.get("categoria") not in ("real_train", "real_test")]
    for nome, chave in (("real_train.npy", "real_train"), ("real_test.npy", "real_test")):
        caminho = C.FEATURES / nome
        a = np.load(caminho, mmap_mode="r")
        entrada = {
            "nome": nome,
            "shape": list(a.shape),
            "dtype": str(a.dtype),
            "bytes": caminho.stat().st_size,
            "caminho": str(caminho.relative_to(C.ROOT)),
            "categoria": chave,
            "split": "treino" if chave == "real_train" else "teste",
            "descricao": (
                "gritos humanos reais de gol (torcedor, gamer, narrador), janela de "
                "2 s com fundo; treino tambem em work/real_train/"
                if chave == "real_train"
                else "gritos humanos reais de gol reservados para teste, janela de 2 s com fundo"
            ),
            "clipes": int(a.shape[0]),
            "horas": round(a.shape[0] * 2.0 / 3600.0, 3),
            "videos": info[chave]["videos"],
            "por_tipo": info[chave]["por_tipo"],
        }
        m["arquivos"].append(entrada)
        m.setdefault("contagens", {})[chave] = int(a.shape[0])
    m.setdefault("gritos_reais", {})
    m["gritos_reais"] = {
        "descricao": "gritos humanos reais de gol, verificados por transcricao",
        "treino": info["real_train"],
        "teste": info["real_test"],
        "split": info["split"],
        "regra": "por video; nenhum video nos dois lados",
    }
    m.setdefault("fontes_audio_bruto", {})["gritos_reais_clipes"] = info["real_train"]["clipes"] + info["real_test"]["clipes"]
    p.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"manifesto: {p}")


def _atualizar_fontes() -> None:
    p = C.ROOT / "FONTES.md"
    videos = _ler_json(VIDEOS_JSON, [])
    novos = [v for v in videos if v.get("novo")]
    linhas = [
        "",
        "## Gritos humanos reais (v2: torcedor, gamer, narrador)",
        "",
        "Baixados por `training/gol/gritos_reais.py --baixar` (yt-dlp, 16 kHz mono).",
        "Cada clipe e verificado por transcricao (faster-whisper small, pt) e/ou",
        "legenda automatica do YouTube; so entra o que tem gol/goo+l/golaco.",
        "Nenhum audio entra no git.",
        "",
        f"- videos novos: {len(novos)}",
        f"- videos reaproveitados de `raw/gol_real/videos`: {sum(1 for v in videos if not v.get('novo'))}",
        "",
        "| tipo | video | URL |",
        "|---|---|---|",
    ]
    for v in sorted(videos, key=lambda v: (v["tipo"], v["id"])):
        linhas.append(f"| {v['tipo']} | {v['id']} | <{v['url']}> |")
    texto = "\n".join(linhas) + "\n"
    if p.exists():
        atual = p.read_text(encoding="utf-8")
        marca = "## Gritos humanos reais (v2"
        if marca in atual:
            atual = atual.split(marca)[0].rstrip() + "\n"
        p.write_text(atual + texto, encoding="utf-8")
    else:
        p.write_text("# Fontes\n" + texto, encoding="utf-8")
    log(f"fontes: {p}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baixar", action="store_true")
    ap.add_argument("--recortar", action="store_true")
    ap.add_argument("--filtrar", action="store_true")
    ap.add_argument("--split", action="store_true")
    ap.add_argument("--features", action="store_true")
    ap.add_argument("--tudo", action="store_true")
    ap.add_argument("--alvo", type=int, default=200, help="videos NOVOS a baixar (>= 120)")
    ap.add_argument("--limite-busca", type=int, default=10)
    ap.add_argument("--legendas", action="store_true",
                    help="busca legendas do YouTube (sujeito a 429; nao e necessario)")
    ap.add_argument("--tipos", default=",".join(TIPOS),
                    help="tipos a baixar (torcedor,gamer,narrador)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--manter-videos", action="store_true")
    ap.add_argument("--limite-videos", type=int, default=0, help="so os N primeiros (teste)")
    ap.add_argument("--min-treino", type=int, default=800)
    ap.add_argument("--min-teste", type=int, default=250)
    ap.add_argument("--min-videos-teste", type=int, default=40)
    args = ap.parse_args()
    if not (args.baixar or args.recortar or args.filtrar or args.split or args.features or args.tudo):
        ap.error("escolha --baixar, --recortar, --filtrar, --split, --features ou --tudo")
    if args.workers > 6:
        ap.error("maximo de 6 processos de CPU")

    if args.tudo or args.baixar:
        tipos = tuple(t.strip() for t in args.tipos.split(",") if t.strip())
        etapa_baixar(args.alvo, args.limite_busca, min(4, args.workers), tipos, args.legendas)
    if args.tudo or args.recortar:
        etapa_recortar(args.workers, args.manter_videos, args.limite_videos)
    if args.tudo or args.filtrar:
        etapa_filtrar(args.workers)
    if args.tudo or args.split:
        etapa_split(args.min_treino, args.min_teste, args.min_videos_teste)
    if args.tudo or args.features:
        etapa_features(args.workers)


if __name__ == "__main__":
    main()
