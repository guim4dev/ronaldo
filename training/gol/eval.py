#!/usr/bin/env python3
"""Avalia o `gol_grito.onnx` no MESMO caminho de producao.

O que e medido, para limiares de 0,30 a 0,90:

- acerto nos gritos de teste: pos_test (Piper jeff + edge-tts, metade limpa e
  metade com ruido de jogo) e gol_real (narradores reais). Um clipe acerta se
  algum chunk passa o limiar. Roda com `ronaldo.detector.WakeWord` nos wavs,
  80 ms por chunk, como na producao (inclui o warmup de 5 chunkos do detector).
- FA/h: validation_set_features.npy do openWakeWord (~11 h), conversa pt-BR,
  jogo e musica (streams de AVALIACAO, >= 8 h cada). Intervalo de 8 s entre
  disparos (100 chunks); taxa observada + limite superior unilateral de 95%
  Poisson (0 alarmes -> ~3/T).
- tudo tambem COM o portao de volume, simulado com a classe de producao
  `ronaldo.grito.PortaoGrito` (ver as aproximacoes em `modelo.py`): streams
  usam o RMS dBFS gravado por chunk; clipes de grito sao simulados em
  referencia+12 dB e a fala normal com "gol" no nivel da referencia.

Uso:
  uv run python eval.py --resumo
  uv run python eval.py --resumo --markdown RESULTADOS.md
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

log = logging.getLogger("gol.eval")

LIMIARES = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
METAS = {"acerto": 0.85, "fa_conversa": 0.5, "fa_jogo_musica": 0.2}
NOMES = {"speech_ptbr": "conversa_mls", "game": "jogo", "music": "musica"}


def _nome_amigavel(bruto: str) -> str:
    return NOMES.get(bruto, bruto)


def _grupo(nome: str) -> str:
    if "conversa" in nome or "speech" in nome:
        return "conversa"
    if nome == "jogo" or nome.startswith("game"):
        return "jogo"
    if nome == "musica" or nome.startswith("music"):
        return "musica"
    return "outro"


def avaliar_validacao(sessao, caminho: Path, limiares: list[float]) -> dict:
    """FA/h no validation_set_features.npy (sem RMS: o portao nao e simulavel)."""
    feats = np.load(caminho, mmap_mode="r")
    if feats.ndim == 3:  # aceita [N,16,96] por completude
        feats = np.asarray(feats).reshape(-1, feats.shape[-1])
    indices, scores = M.scores_stream(sessao, feats, [(0, len(feats))])
    horas = len(indices) * M.PASSO_S / 3600.0
    saida = {"chunks": int(len(indices)), "horas": round(horas, 3), "por_limiar": {}}
    for limiar in limiares:
        k = len(M.contar_disparos(indices, scores, limiar))
        taxa, limite = M.fa_por_hora(k, horas)
        saida["por_limiar"][limiar] = {
            "sem": {"disparos": k, "fa_h": taxa, "limite95": limite},
            "com": None,  # sem RMS no arquivo do openWakeWord: ver RESULTADOS.md
        }
    return saida


def descobrir_streams(dados: Path) -> list[tuple[str, Path, Path, dict]]:
    """Acha todo stream_*_avaliacao_features.npy com o _rms correspondente.

    A categoria nova (ex.: conversa de futebol multi-falante) entra sozinha:
    basta o par `stream_<nome>_avaliacao_{features,rms}.npy` existir. O meta e
    opcional (a avaliacao so precisa de chunks, RMS e, se houver, o numero de
    fontes).
    """
    pasta = dados / "features"
    itens = []
    for feat_p in sorted(pasta.glob("stream_*_avaliacao_features.npy")):
        bruto = feat_p.name[len("stream_") : -len("_avaliacao_features.npy")]
        rms_p = pasta / f"stream_{bruto}_avaliacao_rms.npy"
        if not rms_p.exists():
            log.warning("stream %s: sem %s; ignorando", feat_p.name, rms_p.name)
            continue
        meta_p = pasta / f"stream_{bruto}_avaliacao_meta.json"
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        itens.append((bruto, feat_p, rms_p, meta))
    return itens


def _limites_arquivos(meta: dict, dados: Path, categoria_bruta: str):
    """Fronteiras (arquivo, inicio, fim) em chunks, quando a ordem e a ordenada.

    O conversor paraleliza por fatias de arquivos: a ordem concatenada e
    arquivos[0::W], arquivos[1::W], ... Se houver <= 8 fontes e W >= fontes
    (caso do jogo: 2 videos), a ordem coincide com a lista ordenada.
    """
    import soundfile as sf

    nomes = list(meta.get("arquivos", []))
    if not nomes or len(nomes) > 8:
        return None
    raiz = dados / "raw" / categoria_bruta
    contagens = []
    for nome in nomes:
        caminho = raiz / "wav" / nome
        if not caminho.exists():
            caminho = raiz / nome
        if not caminho.exists():
            return None
        contagens.append(int(sf.info(str(caminho)).frames) // M.CHUNK)
    if sum(contagens) != int(meta["chunks"]):
        return None
    limites, inicio = [], 0
    for nome, n in zip(nomes, contagens):
        limites.append((nome, inicio, inicio + n))
        inicio += n
    return limites


def avaliar_streams(sessao, dados: Path, limiares: list[float], PortaoGrito) -> dict:
    saida = {}
    itens = descobrir_streams(dados)
    if not itens:
        raise SystemExit(f"nenhum stream_*_avaliacao_features.npy em {dados / 'features'}")
    for bruto, feat_p, rms_p, meta in itens:
        nome = _nome_amigavel(bruto)
        feats = np.load(feat_p, mmap_mode="r")
        rms = np.load(rms_p, mmap_mode="r")
        # O conversor paralelo nao registra a ordem da concatenacao dos
        # arquivos; o stream e avaliado como uma sessao continua.
        limites = _limites_arquivos(meta, dados, bruto) if meta else None
        t0 = time.time()
        resultado = M.avaliar_stream(
            sessao, feats, rms, None, limiares, PortaoGrito,
            detalhar=(nome == "jogo"), limites_arquivos=limites,
        )
        resultado["categoria"] = nome
        resultado["arquivo"] = feat_p.name
        resultado["arquivos"] = int(meta.get("fontes", 0))
        resultado["segundos"] = round(time.time() - t0, 1)
        resultado["limites_arquivos"] = limites is not None
        saida[nome] = resultado
        log.warning(
            "%s: %.2f h, %d chunks (%.0fs)",
            nome, resultado["horas"], resultado["chunks"], resultado["segundos"],
        )
    return saida


def combinar(saidas: list[dict], limiares: list[float]) -> dict:
    """Soma disparos e horas de varios streams do mesmo grupo."""
    if not saidas:
        return {"horas": 0.0, "chunks": 0, "por_limiar": {}}
    horas = sum(s["horas"] for s in saidas)
    combinado = {"horas": round(horas, 4), "chunks": sum(s["chunks"] for s in saidas), "por_limiar": {}}
    for limiar in limiares:
        item = {}
        for modo in ("sem", "com"):
            k = sum(s["por_limiar"][limiar][modo]["disparos"] for s in saidas)
            taxa, limite = M.fa_por_hora(k, horas)
            item[modo] = {"disparos": k, "fa_h": taxa, "limite95": limite}
        combinado["por_limiar"][limiar] = item
    return combinado


# --------------------------------------------------------------------------- #
# clipes
# --------------------------------------------------------------------------- #
def _int16(caminho: Path) -> np.ndarray:
    import soundfile as sf

    audio, sr = sf.read(str(caminho), dtype="int16", always_2d=True)
    audio = audio.mean(axis=1).astype(np.int16)
    if sr != M.SR:
        raise SystemExit(f"{caminho}: {sr} Hz (precisa 16 kHz)")
    return audio


def notas_do_clipe(modelo, audio: np.ndarray) -> np.ndarray:
    """Notas chunk a chunk pelo caminho de producao (WakeWord.scores)."""
    nome = modelo.names[0]
    modelo.reset()
    notas = []
    for i in range(0, len(audio) - M.CHUNK + 1, M.CHUNK):
        notas.append(modelo.scores(audio[i : i + M.CHUNK])[nome])
    return np.asarray(notas, dtype=np.float32)


def avaliar_clipes(modelo, caminhos: list[Path], limiares: list[float],
                   PortaoGrito, com_portao: bool = True) -> dict:
    if not caminhos:
        return {"clipes": 0, "segundos": 0.0, "por_limiar": {
            limiar: {"sem": {"acertos": 0, "taxa": 0.0}, "com": {"acertos": 0, "taxa": 0.0}}
            for limiar in limiares}}
    notas_max = np.full(len(caminhos), np.nan, dtype=np.float32)
    notas_ultima = np.full(len(caminhos), np.nan, dtype=np.float32)
    liberado = np.zeros(len(caminhos), dtype=bool)
    t0 = time.time()
    for i, caminho in enumerate(caminhos):
        audio = _int16(caminho)
        notas = notas_do_clipe(modelo, audio)
        notas_max[i] = float(np.max(notas)) if len(notas) else 0.0
        notas_ultima[i] = float(notas[-1]) if len(notas) else 0.0
        if com_portao and PortaoGrito is not None:
            portao = M.preparar_portao(PortaoGrito)
            liberado[i] = M.portao_libera_grito(portao, float(notas_max[i]))
        else:
            liberado[i] = True
        if (i + 1) % 250 == 0:
            log.info("  clipes: %d/%d (%.0fs)", i + 1, len(caminhos), time.time() - t0)
    saida = {"clipes": len(caminhos), "segundos": round(time.time() - t0, 1), "por_limiar": {}}
    for limiar in limiares:
        sem = notas_max >= limiar
        final = notas_ultima >= limiar
        saida["por_limiar"][limiar] = {
            "sem": {"acertos": int(sem.sum()), "taxa": float(sem.mean()) if len(sem) else float("nan")},
            "com": {
                "acertos": int((sem & liberado).sum()),
                "taxa": float((sem & liberado).mean()) if len(sem) else float("nan"),
            },
            "ultima": {
                "acertos": int(final.sum()),
                "taxa": float(final.mean()) if len(final) else float("nan"),
            },
        }
    return saida


def anotar_gate_negativos(portao, modelo, caminhos: list[Path], limiares: list[float]) -> dict:
    """Fala normal com 'gol' no nivel da referencia: o portao tem que barrar."""
    notas_max = np.full(len(caminhos), np.nan, dtype=np.float32)
    t0 = time.time()
    for i, caminho in enumerate(caminhos):
        audio = _int16(caminho)
        notas = notas_do_clipe(modelo, audio)
        notas_max[i] = float(np.max(notas)) if len(notas) else 0.0
        if (i + 1) % 250 == 0:
            log.info("  negativos: %d/%d (%.0fs)", i + 1, len(caminhos), time.time() - t0)
    saida = {"clipes": len(caminhos), "por_limiar": {}}
    for limiar in limiares:
        dispara = notas_max >= limiar
        liberado = 0
        for nota in notas_max[dispara]:
            if M.portao_libera_fala(portao, float(nota)):
                liberado += 1
        saida["por_limiar"][limiar] = {
            "sem": {"disparos": int(dispara.sum())},
            "com": {"disparos": liberado},
        }
    return saida


def avaliar_features_curtas(sessao, caminho: Path, limiares: list[float], PortaoGrito) -> dict:
    """Clipes ja convertidos em features (ex.: real_test.npy).

    Aceita [N, 16, 96] (uma janela por clipe) ou [N, T, 96] (varias janelas;
    vale o maximo por clipe, como na producao).
    """
    feats = np.load(caminho, mmap_mode="r")
    if feats.ndim == 3:
        n, t = feats.shape[0], feats.shape[1]
        notas = M.scores_janelas(sessao, np.asarray(feats).reshape(-1, feats.shape[-1]))
        notas = notas.reshape(n, t).max(axis=1)
    else:
        notas = M.scores_janelas(sessao, feats)
    saida = {"clipes": int(len(notas)), "segundos": 0.0, "por_limiar": {}}
    for limiar in limiares:
        sem = notas >= limiar
        saida["por_limiar"][limiar] = {
            "sem": {"acertos": int(sem.sum()), "taxa": float(sem.mean())},
            "com": {"acertos": int(sem.sum()), "taxa": float(sem.mean())},
            "ultima": {"acertos": int(sem.sum()), "taxa": float(sem.mean())},
        }
    return saida


def videos_treino_real(dados: Path) -> set[str]:
    """IDs de video que entraram no real_train (para nao avaliar o gol_real neles)."""
    videos: set[str] = set()

    def coletar(obj):
        if isinstance(obj, list):
            for it in obj:
                coletar(it)
        elif isinstance(obj, dict):
            if obj.get("video"):
                videos.add(str(obj["video"]))
            for chave in ("itens", "clipes", "real_train"):
                if chave in obj:
                    coletar(obj[chave])

    pasta = dados / "work" / "real_train"
    if pasta.exists():
        for arq in pasta.rglob("*.json"):
            try:
                coletar(json.loads(arq.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                continue
    man = dados / "MANIFESTO.json"
    if man.exists():
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
            if "real_train" in m:
                coletar(m["real_train"])
        except Exception:  # noqa: BLE001
            pass
    return videos


def selecionar_clipes(dados: Path, tipo: str | None, limite: int, seed: int = 7) -> list[Path]:
    import random

    pasta = dados / "work" / "neg_train"
    receitas_p = pasta / "receitas.json"
    if not receitas_p.exists():
        return []
    receitas = json.loads(receitas_p.read_text(encoding="utf-8"))
    itens = [r for r in receitas if tipo is None or r["receita"].get("tipo") == tipo]
    random.Random(seed).shuffle(itens)
    return [Path(r["arquivo"]) for r in itens[:limite] if Path(r["arquivo"]).exists()]


# --------------------------------------------------------------------------- #
# escolha do limiar e relatorio
# --------------------------------------------------------------------------- #
def acerto_total(clipes: dict, limiar: float) -> tuple[int, int]:
    acertos = sum(c["por_limiar"][limiar]["com"]["acertos"] for c in clipes.values())
    total = sum(c["clipes"] for c in clipes.values())
    return acertos, total


def escolher_limiar(resultado: dict, limiares: list[float]) -> dict:
    linhas = []
    for limiar in limiares:
        acertos, total = acerto_total(resultado["clipes"], limiar)
        acerto = acertos / total if total else 0.0
        fa_conv = resultado["conversa"]["por_limiar"][limiar]["com"]["fa_h"]
        fa_jm = resultado["jogo_musica"]["por_limiar"][limiar]["com"]["fa_h"]
        metas = {
            "acerto": acerto >= METAS["acerto"],
            "fa_conversa": fa_conv <= METAS["fa_conversa"],
            "fa_jogo_musica": fa_jm <= METAS["fa_jogo_musica"],
        }
        linhas.append({
            "limiar": limiar,
            "acerto": acerto,
            "acertos": acertos,
            "total": total,
            "fa_conversa": fa_conv,
            "fa_jogo_musica": fa_jm,
            "metas": metas,
            "cumpriu": sum(metas.values()),
        })
    # A meta de conversa vale para o conjunto somado (MLS + futebol); cada
    # conjunto aparece na tabela e o pior tambem e reportado no relatorio.
    viaveis = [x for x in linhas if x["cumpriu"] == 3]
    if viaveis:
        escolhido = max(viaveis, key=lambda x: (x["acerto"], -x["fa_conversa"] - x["fa_jogo_musica"]))
    else:
        escolhido = max(linhas, key=lambda x: (x["cumpriu"], x["acerto"], -x["fa_conversa"] - x["fa_jogo_musica"]))
    return {"escolhido": escolhido, "linhas": linhas}


def _fmt_fa(item) -> str:
    if item is None:
        return "n/d"
    fa = item["fa_h"]
    up = item["limite95"]
    k = item["disparos"]
    return f"{fa:.2f} ({k}; <= {up:.2f})"


def _fmt_acc(item) -> str:
    return f"{100 * item['taxa']:.1f}% ({item['acertos']}/{item['clipes'] if 'clipes' in item else '-'})"


def _ordem_streams(nomes: list[str]) -> list[str]:
    preferencia = ["conversa_mls", "jogo", "musica"]
    resto = sorted(n for n in nomes if n not in preferencia)
    return [n for n in preferencia if n in nomes] + resto


def tabela_markdown(resultado: dict, limiares: list[float], com_portao: bool) -> str:
    modo = "com" if com_portao else "sem"
    nomes = _ordem_streams(list(resultado["streams"]))
    rotulos = {"sintetico_limpo": "sintetico limpo", "sintetico_ruido": "sintetico ruido",
               "narradores": "narradores reais", "real_teste": "real teste (novo)"}
    chaves_clipes = [k for k in ("sintetico_limpo", "sintetico_ruido", "narradores", "real_teste")
                     if k in resultado["clipes"]]
    cab = ["limiar", *[rotulos[k] for k in chaves_clipes], "total", "validation", *nomes, "jogo+musica"]
    linhas = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    for limiar in limiares:
        c = resultado["clipes"]
        def acerto(chave):
            item = dict(c[chave]["por_limiar"][limiar][modo])
            item["clipes"] = c[chave]["clipes"]
            return _fmt_acc(item)
        acertos, total = acerto_total(c, limiar)
        total_txt = f"{100 * acertos / total:.1f}% ({acertos}/{total})" if total else "n/d"
        val = resultado["validacao"]["por_limiar"][limiar][modo]
        val_txt = "n/d" if val is None else _fmt_fa(val)
        celulas = [f"{limiar:.2f}", *[acerto(k) for k in chaves_clipes], total_txt, val_txt]
        for nome in nomes:
            celulas.append(_fmt_fa(resultado["streams"][nome]["por_limiar"][limiar][modo]))
        celulas.append(_fmt_fa(resultado["jogo_musica"]["por_limiar"][limiar][modo]))
        linhas.append("| " + " | ".join(celulas) + " |")
    return "\n".join(linhas)


def imprimir_resumo(resultado: dict, escolha: dict) -> None:
    limiares = resultado["limiares"]
    print()
    print("=" * 100)
    print("gol_grito — avaliacao (disparos com intervalo de 8 s; FA/h observada (n; limite 95% Poisson))")
    print("=" * 100)
    print("\nSEM portao de volume\n")
    print(tabela_markdown(resultado, limiares, com_portao=False))
    print("\nCOM portao de volume (grito simulado em referencia+12 dB)\n")
    print(tabela_markdown(resultado, limiares, com_portao=True))
    e = escolha["escolhido"]
    print("\n" + "-" * 100)
    print(f"LIMIAR SUGERIDO: {e['limiar']:.2f}")
    print(
        f"  acerto (com portao): {100 * e['acerto']:.1f}% ({e['acertos']}/{e['total']}) "
        f"[meta >= 85%: {'OK' if e['metas']['acerto'] else 'NAO'}]"
    )
    print(
        f"  FA/h conversa: {e['fa_conversa']:.2f} [meta <= 0,5: {'OK' if e['metas']['fa_conversa'] else 'NAO'}]   "
        f"jogo+musica: {e['fa_jogo_musica']:.2f} [meta <= 0,2: {'OK' if e['metas']['fa_jogo_musica'] else 'NAO'}]"
    )
    print(f"  metas cumpridas: {e['cumpriu']}/3")
    print("-" * 100)


def markdown_completo(resultado: dict, escolha: dict) -> str:
    limiares = resultado["limiares"]
    e = escolha["escolhido"]
    meta = lambda ok: "bate" if ok else "NAO bate"  # noqa: E731
    validacao = resultado["validacao"]
    streams = resultado["streams"]
    c = resultado["clipes"]
    linhas_streams = []
    for nome in _ordem_streams(list(streams)):
        s = streams[nome]
        arquivo = s.get("arquivo", "")
        linhas_streams.append(
            f"| {nome} | {s['horas']:.2f} h | {s.get('arquivos', 0)} arquivo(s) | `{arquivo}` |"
        )
    tabela_conjuntos_streams = "\n".join(linhas_streams)
    fa_pior = max(
        (streams[n]["por_limiar"][e["limiar"]]["com"]["fa_h"] for n in streams
         if _grupo(n) == "conversa"),
        default=float("nan"),
    )
    pior_nome = "n/d"
    for n in streams:
        if _grupo(n) == "conversa" and streams[n]["por_limiar"][e["limiar"]]["com"]["fa_h"] == fa_pior:
            pior_nome = n
            break
    linhas_conversa = "\n".join(
        f"  - {n}: {streams[n]['por_limiar'][e['limiar']]['com']['fa_h']:.2f} FA/h com portao "
        f"({streams[n]['horas']:.2f} h)"
        for n in _ordem_streams(list(streams)) if _grupo(n) == "conversa"
    )
    chaves_clipes = [k for k in ("sintetico_limpo", "sintetico_ruido", "narradores", "real_teste")
                     if k in c]
    linhas_janela = []
    for k in chaves_clipes:
        item = c[k]["por_limiar"][e["limiar"]]
        linhas_janela.append(
            f"| {k} | {100 * item['ultima']['taxa']:.1f}% ({item['ultima']['acertos']}/{c[k]['clipes']}) "
            f"| {100 * item['com']['taxa']:.1f}% ({item['com']['acertos']}/{c[k]['clipes']}) |"
        )
    tabela_janela = "\n".join(linhas_janela)
    detalhes_jogo = streams.get("jogo", {}).get("detalhes", {}).get(e["limiar"], [])
    linhas_jogo = [
        f"| {d.get('arquivo') or 'n/d'} | {d['tempo_arquivo_s'] if d.get('tempo_arquivo_s') is not None else 'n/d'} "
        f"| {d['tempo_stream_s']:.2f} | {d['score']:.3f} | {d['nivel_db']:.1f} |"
        for d in detalhes_jogo
    ]
    tabela_jogo = "\n".join(linhas_jogo)
    fila_real = ""
    real_txt = ""
    if "real_teste" in c:
        fila_real = f"| real teste (novo) | {c['real_teste']['clipes']} | `features/real_test.npy` |"
        real_txt = (f", real teste {100 * c['real_teste']['por_limiar'][e['limiar']]['com']['taxa']:.1f}%")
    texto = f"""# Resultados do `gol_grito`

Gerado por `uv run python eval.py --resumo --markdown RESULTADOS.md` em
{time.strftime("%Y-%m-%d %H:%M")}. Modelo: `models/gol_grito.onnx`
({resultado["modelo_kb"]:.1f} KB, entrada [1, 16, 96], saida [1, 1]).

## Limiar sugerido: **{e["limiar"]:.2f}**

| meta | valor | alvo | resultado |
|---|---|---|---|
| acerto nos gritos de teste (com portao) | {100 * e["acerto"]:.1f}% ({e["acertos"]}/{e["total"]}) | >= 85% | {meta(e["metas"]["acerto"])} |
| FA/h conversa pt-BR (com portao, todos os conjuntos) | {e["fa_conversa"]:.2f} | <= 0,5 | {meta(e["metas"]["fa_conversa"])} |
| FA/h jogo+musica (com portao) | {e["fa_jogo_musica"]:.2f} | <= 0,2 | {meta(e["metas"]["fa_jogo_musica"])} |
| metas cumpridas | {e["cumpriu"]}/3 | 3/3 | {"OK" if e["cumpriu"] == 3 else "parcial"} |

## Tabelas

"Sem portao" = so o classificador, com intervalo minimo de 8 s entre disparos.
"Com portao" = a mesma contagem depois do portao de volume de producao
(`ronaldo.grito.PortaoGrito`, simulado). FA/h entre parenteses: disparos
contados; limite superior unilateral de 95% Poisson.

### Sem portao de volume

{tabela_markdown(resultado, limiares, com_portao=False)}

### Com portao de volume

{tabela_markdown(resultado, limiares, com_portao=True)}

### Alinhamento: ultima janela vs maximo por chunk (limiar sugerido)

| conjunto | so a ultima janela | maximo por chunk |
|---|---|---|
{tabela_janela}

### Disparos no jogo no limiar sugerido (com portao)

`arquivo` e `tempo no arquivo` so aparecem quando o stream tem <= 8 fontes
(2 videos no jogo); o tempo no stream sempre aparece. O portao deixa passar
somente os disparos acima da referencia de fala.

| arquivo | tempo no arquivo (s) | tempo no stream (s) | nota | nivel (dBFS) |
|---|---|---|---|---|
{tabela_jogo}

## Conjuntos

| conjunto | clipes | fonte |
|---|---|---|
| sintetico limpo | {c["sintetico_limpo"]["clipes"]} | pos_test, vozes reservadas (Piper jeff + edge-tts), sem ruido |
| sintetico ruido | {c["sintetico_ruido"]["clipes"]} | pos_test com ruido de jogo (SNR 0-20 dB) |
| narradores reais | {c["narradores"]["clipes"]} | `raw/gol_real/clips` (videos publicos, uso local) |
{fila_real}
{tabela_conjuntos_streams}
| validation openWakeWord | {validacao["horas"]:.2f} h | `validation_set_features.npy` |
| fala normal com "gol" | {resultado["negativos_fala"]["clipes"]} clipes | amostra de `work/neg_train` (tipo fala_normal) |
| palavras curtas gritadas | {resultado["negativos_grito"]["clipes"]} clipes | amostra de `work/neg_train` (tipo palavra_gritada) |

## O que bate e o que nao bate

- Acerto nos gritos de teste (com portao) no limiar sugerido:
  {100 * e["acerto"]:.1f}% — {meta(e["metas"]["acerto"])} a meta de 85%.
  Por conjunto: sintetico limpo {100 * c["sintetico_limpo"]["por_limiar"][e["limiar"]]["com"]["taxa"]:.1f}%,
  sintetico com ruido {100 * c["sintetico_ruido"]["por_limiar"][e["limiar"]]["com"]["taxa"]:.1f}%,
  narradores reais {100 * c["narradores"]["por_limiar"][e["limiar"]]["com"]["taxa"]:.1f}%{real_txt}.
- FA/h observada com portao no limiar sugerido: conversa {e["fa_conversa"]:.2f}
  ({meta(e["metas"]["fa_conversa"])} a meta de 0,5), jogo+musica {e["fa_jogo_musica"]:.2f}
  ({meta(e["metas"]["fa_jogo_musica"])} a meta de 0,2).
  Por conjunto de conversa (o pior e `{pior_nome}`, {fa_pior:.2f} FA/h):
{linhas_conversa}
- **Conversa MLS e de um falante so.** A conversa de futebol multi-falante entrou
  como conjunto proprio para medir a generalizacao entre falantes; a meta de
  conversa vale para a soma dos conjuntos.
- Fala normal com "gol" no nivel da referencia: o portao barra
  {resultado["negativos_fala"]["por_limiar"][e["limiar"]]["sem"]["disparos"] - resultado["negativos_fala"]["por_limiar"][e["limiar"]]["com"]["disparos"]}
  de
  {resultado["negativos_fala"]["por_limiar"][e["limiar"]]["sem"]["disparos"]} disparos
  do classificador em {resultado["negativos_fala"]["clipes"]} clipes de fala normal (amostra).
- Palavras curtas gritadas que nao sao "gol": o portao barra
  {resultado["negativos_grito"]["por_limiar"][e["limiar"]]["sem"]["disparos"] - resultado["negativos_grito"]["por_limiar"][e["limiar"]]["com"]["disparos"]}
  de
  {resultado["negativos_grito"]["por_limiar"][e["limiar"]]["sem"]["disparos"]} disparos
  do classificador em {resultado["negativos_grito"]["clipes"]} clipes (amostra).

## Aproximacoes (importantes)

1. **Portao nos streams.** O stream so tem o RMS dBFS por chunk (nao ha audio).
   O chunk sintetico tem amplitude constante com o mesmo RMS, porque o portao de
   producao so olha o RMS. O VAD e aproximado por `RMS > piso + 10 dB`, com piso =
   percentil 10 do RMS em blocos de ~2 min. O stream inteiro e tratado como uma
   sessao continua: o conversor de features paraleliza por arquivo e nao registra
   a ordem da concatenacao, entao nao ha fronteira de arquivo confiavel. Os
   eventos de fronteira sao ~1 janela por arquivo (desprezivel no total).
2. **validation_set_features** (~11 h) nao tem RMS: a coluna COM portao e `n/d`.
   O numero sem portao e o que vale para esse conjunto; o portao so pode reduzir
   disparos, nunca aumentar.
3. **Clipes de grito.** A fala normal simulada tem RMS de referencia -26 dBFS
   (25 s para a referencia do portao); o grito e simulado a referencia+12 dB.
   A fala normal com "gol" e avaliada no nivel da referencia.
4. **Warmup.** Nos streams as 15 primeiras janelas sao descartadas (historico
   incompleto); nos clipes vale o warmup real do `WakeWord` (5 primeiros chunkos
   com nota 0).
5. **Alcance.** Os numeros provam vozes sinteticas e narradores reais. **Nao
   provam a voz do Guima**: isso depende do teste ao vivo
   (`tools/grito_ao_vivo.py`, 10 gritos + 2 min de conversa, nada gravado).
   As metas devem ser conferidas contra o alvo; se nao baterem, o deploy espera
   a aceitacao ao vivo ou uma ordem explicita do Guima.
6. **Arquivo e tempo no jogo.** O conversor paralelo nao guarda a ordem da
   concatenacao. No jogo ha 2 videos e 6 fatias: a ordem concatenada coincide
   com a lista ordenada, entao `arquivo` e `tempo no arquivo` saem exatos. Para
   os outros streams (muitos arquivos) a coluna nao se aplica.

## Modelo e licenca

`models/gol_grito.onnx` — CC BY-NC-SA 4.0 (c) Thiago Guimaraes, os mesmos
termos do `ronaldo_ptbr.onnx` (ver `models/LICENSES.md`). Pesos treinados nesta
maquina; nenhum audio de terceiros entra no repositorio.
"""
    return texto


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dados", default=str(Path.home() / "data" / "gol"))
    ap.add_argument("--modelo", default=str(REPO / "models" / "gol_grito.onnx"))
    ap.add_argument("--limiares", default=",".join(f"{x:g}" for x in LIMIARES))
    ap.add_argument("--max-clipes-neg", type=int, default=1000)
    ap.add_argument("--resumo", action="store_true")
    ap.add_argument("--markdown", default="", help="escreve o relatorio nesse caminho")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    dados = Path(args.dados).expanduser()
    modelo_p = Path(args.modelo)
    if not modelo_p.exists():
        raise SystemExit(f"falta {modelo_p}; rode train.py")
    limiares = [float(x) for x in args.limiares.split(",") if x.strip()]
    sessao = M.sessao_onnx(modelo_p, threads=2)

    PortaoGrito = M.carregar_portao()
    logging.getLogger("ronaldo.grito").setLevel(logging.ERROR)

    import onnxruntime  # noqa: F401
    from ronaldo.detector import WakeWord

    modelo = WakeWord(modelo_p, REPO / "models")
    t0 = time.time()

    log.warning("avaliacao: validation_set")
    validacao = avaliar_validacao(
        sessao, dados / "raw" / "openwakeword" / "validation_set_features.npy", limiares
    )
    log.warning("avaliacao: streams de avaliacao")
    streams = avaliar_streams(sessao, dados, limiares, PortaoGrito)
    conversas = [v for k, v in streams.items() if _grupo(k) == "conversa"]
    jogo_musica = combinar(
        [v for k, v in streams.items() if _grupo(k) in ("jogo", "musica")], limiares
    )
    conversa = combinar(conversas, limiares)

    log.warning("avaliacao: clipes de teste")
    receitas_p = dados / "work" / "pos_test" / "receitas.json"
    receitas = json.loads(receitas_p.read_text(encoding="utf-8")) if receitas_p.exists() else []
    limpos = [Path(r["arquivo"]) for r in receitas
              if r["receita"].get("snr_db") is None and Path(r["arquivo"]).exists()]
    ruidos = [Path(r["arquivo"]) for r in receitas
              if r["receita"].get("snr_db") is not None and Path(r["arquivo"]).exists()]
    reais = sorted((dados / "raw" / "gol_real" / "clips").glob("*.wav"))
    vids_treino = videos_treino_real(dados)
    if vids_treino:
        antes = len(reais)
        reais = [p for p in reais if not any(v in p.name for v in vids_treino)]
        log.warning("gol_real: %d -> %d clipes (videos do real_train fora)", antes, len(reais))
    if not limpos and not ruidos:
        todos = sorted((dados / "work" / "pos_test").glob("*.wav"))
        limpos = todos
    clipes = {
        "sintetico_limpo": avaliar_clipes(modelo, limpos, limiares, PortaoGrito),
        "sintetico_ruido": avaliar_clipes(modelo, ruidos, limiares, PortaoGrito),
        "narradores": avaliar_clipes(modelo, reais, limiares, PortaoGrito),
    }
    real_test_p = dados / "features" / "real_test.npy"
    if real_test_p.exists():
        clipes["real_teste"] = avaliar_features_curtas(sessao, real_test_p, limiares, PortaoGrito)
        log.warning("real_test: %d clipes de %s", clipes["real_teste"]["clipes"], real_test_p.name)

    log.warning("avaliacao: clipes negativos (amostra)")
    neg_fala_dir = selecionar_clipes(dados, "fala_normal", args.max_clipes_neg)
    neg_grito_dir = selecionar_clipes(dados, "palavra_gritada", max(200, args.max_clipes_neg // 2))
    portao_neg = M.preparar_portao(PortaoGrito)
    neg_fala = anotar_gate_negativos(portao_neg, modelo, neg_fala_dir, limiares)
    neg_grito = anotar_gate_negativos(portao_neg, modelo, neg_grito_dir, limiares)

    resultado = {
        "modelo": str(modelo_p),
        "modelo_kb": modelo_p.stat().st_size / 1024,
        "limiares": limiares,
        "validacao": validacao,
        "streams": streams,
        "conversa": conversa,
        "jogo_musica": jogo_musica,
        "clipes": clipes,
        "negativos_fala": neg_fala,
        "negativos_grito": neg_grito,
        "segundos": round(time.time() - t0, 1),
    }
    escolha = escolher_limiar(resultado, limiares)
    resultado["sugerido"] = escolha["escolhido"]
    resultado["selecao"] = escolha["linhas"]

    if args.resumo:
        imprimir_resumo(resultado, escolha)
    if args.markdown:
        Path(args.markdown).write_text(markdown_completo(resultado, escolha), encoding="utf-8")
        log.warning("relatorio em %s", args.markdown)
    destino = Path(args.json) if args.json else dados / "avaliacao.json"
    destino.write_text(json.dumps(resultado, indent=1, ensure_ascii=False), encoding="utf-8")
    log.warning("json em %s (%.0fs)", destino, time.time() - t0)


if __name__ == "__main__":
    main()
