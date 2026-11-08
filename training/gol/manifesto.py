#!/usr/bin/env python3
"""Escreve ~/data/gol/MANIFESTO.json a partir do que esta em disco.

Le os .npy com mmap (o de features ACAV tem 17 GB: nunca carregar inteiro) e
confere que cada arquivo citado existe e tem a forma esperada. Falha se faltar
alguma peca exigida pelo contrato (>= 8 h de avaliacao por categoria, 20 mil
positivos/negativos de treino, 1 000 positivos de teste, >= 60 gritos reais).

Uso: uv run python manifesto.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import comum as C

MANIFESTO = C.ROOT / "MANIFESTO.json"
RESUMO = C.ROOT / "RESUMO.md"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def info_npy(caminho: Path) -> dict:
    a = np.load(caminho, mmap_mode="r")
    return {"nome": caminho.name, "shape": list(a.shape), "dtype": str(a.dtype),
            "bytes": caminho.stat().st_size, "caminho": str(caminho.relative_to(C.ROOT))}


def exigir(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise SystemExit("FALTA: " + mensagem)


def main() -> None:
    arquivos: list[dict] = []
    horas: dict[str, dict[str, float]] = {}
    contagens: dict[str, int] = {}

    # ---- curtas: positivos e negativos sinteticos
    for nome, categoria, papel in (
        ("pos_train.npy", "positivo_sintetico", "treino"),
        ("neg_train.npy", "negativo_sintetico", "treino"),
        ("pos_test.npy", "positivo_sintetico", "teste"),
    ):
        p = C.FEATURES / nome
        exigir(p.exists(), f"{p} (rode features.py --curtos)")
        d = info_npy(p)
        d.update({"categoria": categoria, "split": papel,
                  "descricao": {
                      "pos_train.npy": "gritos sinteticos: Piper faber/edresson/cadu com aumento de grito",
                      "neg_train.npy": "fala normal com gol/palavras parecidas + palavras curtas gritadas",
                      "pos_test.npy": "gritos de vozes reservadas: Piper jeff + edge-tts pt-BR/pt-PT",
                  }[nome],
                  "clipes": int(d["shape"][0]),
                  "horas": round(d["shape"][0] * 2.0 / 3600.0, 3)})
        arquivos.append(d)
        contagens[nome.replace(".npy", "")] = int(d["shape"][0])

    exigir(contagens.get("pos_train", 0) >= 19000, f"positivos de treino: {contagens.get('pos_train')}")
    exigir(contagens.get("neg_train", 0) >= 19000, f"negativos de treino: {contagens.get('neg_train')}")
    exigir(contagens.get("pos_test", 0) >= 900, f"positivos de teste: {contagens.get('pos_test')}")

    # ---- longos: streaming por categoria e split
    for categoria_disco, categoria, nome_horas in (
        ("speech_ptbr", "conversa_ptbr", "conversa"),
        ("game", "jogo_videogame", "jogo"),
        ("music", "musica", "musica"),
    ):
        horas[nome_horas] = {}
        for split in ("treino", "avaliacao"):
            meta_p = C.FEATURES / f"stream_{categoria_disco}_{split}_meta.json"
            exigir(meta_p.exists(), f"{meta_p} (rode features.py --streaming)")
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            feat = C.ROOT / meta["arquivo_features"]
            rms = C.ROOT / meta["arquivo_rms"]
            exigir(feat.exists() and rms.exists(), f"{feat} / {rms}")
            d = info_npy(feat)
            d_rms = info_npy(rms)
            exigir(d["shape"] == [meta["chunks"], 96], f"{feat.name}: shape {d['shape']} != meta")
            exigir(d_rms["shape"] == [meta["chunks"]], f"{rms.name}: shape {d_rms['shape']}")
            d.update({"categoria": categoria, "split": split,
                      "descricao": f"streaming 80 ms de {nome_horas} (1 linha [96] por chunk)",
                      "chunks": meta["chunks"], "fontes": meta["fontes"],
                      "horas": meta["horas"],
                      "rms_dbfs": d_rms["caminho"],
                      "arquivos_de_audio": meta["arquivos"]})
            arquivos.append(d)
            arquivos.append({**d_rms, "categoria": categoria, "split": split,
                             "descricao": f"RMS dBFS por chunk de {nome_horas} ({split})"})
            horas[nome_horas][split] = meta["horas"]
            contagens[f"chunks_{nome_horas}_{split}"] = meta["chunks"]
        exigir(horas[nome_horas]["avaliacao"] >= 8.0,
               f"{nome_horas}: avaliacao {horas[nome_horas]['avaliacao']:.2f} h (< 8 h)")
        exigir(horas[nome_horas]["treino"] >= 8.0,
               f"{nome_horas}: treino {horas[nome_horas]['treino']:.2f} h (< 8 h)")

    # ---- conversa de futebol: SO avaliacao (nao entra no treino)
    horas["conversa_futebol"] = {}
    meta_p = C.FEATURES / "stream_conversa_futebol_avaliacao_meta.json"
    exigir(meta_p.exists(), f"{meta_p} (rode features.py --conversa-futebol)")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    feat = C.ROOT / meta["arquivo_features"]
    rms = C.ROOT / meta["arquivo_rms"]
    exigir(feat.exists() and rms.exists(), f"{feat} / {rms}")
    d = info_npy(feat)
    d_rms = info_npy(rms)
    exigir(d["shape"] == [meta["chunks"], 96], f"{feat.name}: shape {d['shape']} != meta")
    exigir(d_rms["shape"] == [meta["chunks"]], f"{rms.name}: shape {d_rms['shape']}")
    exigir(meta.get("so_avaliacao") is True, "conversa_futebol tem que ser so avaliacao")
    d.update({"categoria": "conversa_futebol", "split": "avaliacao",
              "descricao": "streaming 80 ms de conversa espontanea pt-BR sobre futebol "
                           "(mesa redonda/podcast), so avaliacao",
              "chunks": meta["chunks"], "fontes": meta["fontes"], "horas": meta["horas"],
              "rms_dbfs": d_rms["caminho"],
              "arquivos_de_audio": meta["arquivos"]})
    arquivos.append(d)
    arquivos.append({**d_rms, "categoria": "conversa_futebol", "split": "avaliacao",
                     "descricao": "RMS dBFS por chunk de conversa de futebol (avaliacao)"})
    horas["conversa_futebol"]["avaliacao"] = meta["horas"]
    contagens["chunks_conversa_futebol_avaliacao"] = meta["chunks"]
    if meta["horas"] < 8.0:
        log(f"AVISO conversa_futebol: {meta['horas']:.2f} h (alvo 8 h; minimo aceito 4 h)")
    exigir(meta["horas"] >= 4.0,
           f"conversa_futebol: avaliacao {meta['horas']:.2f} h (< 4 h)")
    for proibido in C.FEATURES.glob("stream_conversa_futebol_treino*"):
        raise SystemExit(f"conversa_futebol nao pode ter treino: {proibido}")

    # ---- externos (nao convertidos aqui)
    externos = []
    acav = C.RAW / "openwakeword" / "openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
    val = C.RAW / "openwakeword" / "validation_set_features.npy"
    exigir(acav.exists(), f"{acav} (rode download.py --etapa openwakeword)")
    exigir(val.exists(), f"{val} (rode download.py --etapa openwakeword)")
    for p, papel, descricao in (
        (acav, "negativo_geral_treino",
         "features ACAV100M do openWakeWord (5.625 M clipes de 2 s) — fala/ruido geral"),
        (val, "avaliacao_falso_alarme",
         "validation_set do openWakeWord (~10.7 h, streaming 80 ms) — FA/h da metrica (a)"),
    ):
        d = info_npy(p)
        d.update({"papel": papel, "descricao": descricao, "externo": True})
        if p.name.startswith("openwakeword_features"):
            d["clipes"] = int(d["shape"][0])
            d["horas"] = round(d["shape"][0] * 2.0 / 3600.0, 1)
        else:
            d["chunks"] = int(d["shape"][0])
            d["horas"] = round(d["shape"][0] * 0.08 / 3600.0, 1)
        externos.append(d)

    # ---- gritos reais (avaliacao)
    clips_reais = sorted((C.RAW / "gol_real" / "clips").glob("*.wav"))
    exigir(len(clips_reais) >= 60, f"gritos reais: {len(clips_reais)} (< 60)")
    import soundfile as sf

    dur_reais = sum(sf.info(str(p)).frames / sf.info(str(p)).samplerate for p in clips_reais)
    contagens["gritos_reais"] = len(clips_reais)

    # ---- gritos humanos reais (treino e teste, split por video)
    real_split = C.FEATURES / "real_split.json"
    real_info = None
    if real_split.exists():
        split = json.loads(real_split.read_text(encoding="utf-8"))
        real_info = {"descricao": "gritos humanos reais de gol, verificados por transcricao",
                     "regra": "por video; nenhum video nos dois lados",
                     "split": "features/real_split.json", "treino": {}, "teste": {}}
        for nome, chave, lado in (("real_train.npy", "real_train", "treino"),
                                  ("real_test.npy", "real_test", "teste")):
            p_real = C.FEATURES / nome
            exigir(p_real.exists(), f"{p_real} (rode gritos_reais.py --features)")
            d = info_npy(p_real)
            d.update({
                "categoria": chave, "split": lado,
                "descricao": "gritos humanos reais de gol (torcedor, gamer, narrador), "
                             "janela de 2 s com fundo",
                "clipes": int(d["shape"][0]),
                "horas": round(d["shape"][0] * 2.0 / 3600.0, 3),
                "videos": len(split[f"videos_{lado}"]),
                "por_tipo": split.get(f"por_tipo_{lado}", {}),
            })
            arquivos.append(d)
            contagens[chave] = int(d["shape"][0])
            real_info[lado] = {"clipes": d["clipes"], "videos": d["videos"],
                               "por_tipo": d["por_tipo"]}

    # ---- vozes e frases
    receitas_pos = C.WORK / "pos_train" / "receitas.json"
    receitas_neg = C.WORK / "neg_train" / "receitas.json"
    vozes_treino = sorted({r["voz"] for r in json.loads(receitas_pos.read_text()) if r.get("origem") == "piper"}) \
        if receitas_pos.exists() else C.VOZES_TREINO
    vozes_teste_edge = sorted({r["voz"] for r in json.loads((C.WORK / "pos_test" / "receitas.json").read_text())
                               if r.get("origem") == "edge"}) if (C.WORK / "pos_test" / "receitas.json").exists() else C.EDGE_TESTE
    vozes_teste_piper = sorted({r["voz"] for r in json.loads((C.WORK / "pos_test" / "receitas.json").read_text())
                                if r.get("origem") == "piper"}) if (C.WORK / "pos_test" / "receitas.json").exists() else C.VOZES_TESTE
    contagens["frases_com_gol"] = len(C.frases_com_gol())
    contagens["frases_parecidas"] = len(C.FRASES_PARECIDAS)
    contagens["frases_neutras"] = len(C.FRASES_NEUTRAS)
    contagens["palavras_gritadas_nao_gol"] = len(C.PALAVRAS_GRITADAS)

    # fontes de audio longo
    def contar(categoria: str) -> int:
        pasta = C.RAW / categoria / "wav"
        if not pasta.exists():
            pasta = C.RAW / categoria
        return len(list(pasta.glob("*.wav"))) if pasta.exists() else 0

    manifesto = {
        "projeto": "gol_grito",
        "objetivo": "detectar grito de gol (gol/gool/gooool/golaco) tocando o tema; sem disparar em fala, jogo ou musica",
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "maquina": "hemocione-one",
        "repo": "guim4dev/ronaldo, branch feat/grito-treino (repo publico: so scripts e docs)",
        "dados_em": str(C.ROOT),
        "pipeline": {
            "fonte_da_verdade": "ronaldo/detector.py (WakeWord._embed_clip e WakeWord.scores)",
            "mel_model": "models/melspectrogram.onnx",
            "embedding_model": "models/embedding_model.onnx",
            "mel_transform": "mel/10 + 2",
            "janela_mel_frames": 76,
            "passo_mel_frames": 8,
            "janela_amostras": 32000,
            "janela_segundos": 2.0,
            "embeddings_por_clipe": 16,
            "dim_embedding": 96,
            "chunk_amostras": 1280,
            "chunk_ms": 80,
            "amostragem": 16000,
            "canais": 1,
            "posicao_do_clipe_na_janela": "fim (o resto e fundo)",
            "features_dtype": "float16 (como o npy ACAV do openWakeWord); float32 na extracao",
            "rms": "20*log10(rms_int16/32768) por chunk, so nos arquivos de avaliacao e treino longos",
        },
        "vozes": {
            "treino": {"piper": vozes_treino, "edge": []},
            "teste": {"piper": vozes_teste_piper, "edge": vozes_teste_edge},
        },
        "split": {
            "curtos": "treino e teste sao gerados separados (vozes disjuntas no teste)",
            "longos": "por fonte: falante MLS (conversa), video (jogo), faixa (musica); nenhuma fonte nos dois lados",
            "detalhe": "features/split_streaming.json",
        },
        "contagens": contagens,
        "horas": horas,
        "duracao_dos_clipes": {
            "curtos_segundos": 2.0,
            "gritos_reais_segundos_max": 3.0,
            "gritos_reais_total_segundos": round(dur_reais, 2),
        },
        "arquivos": arquivos,
        "externos": externos,
        "fontes_audio_bruto": {
            "conversa_ptbr": contar("speech_ptbr"),
        "conversa_futebol": contar("conversa_futebol"),
            "jogo": contar("game"),
            "musica": contar("music"),
            "ruido": contar("noise"),
            "rir": contar("rir"),
            "gol_real_clipes": len(clips_reais),
        },
        "fontes_md": "FONTES.md",
    }
    if real_info is not None:
        manifesto["gritos_reais"] = real_info
        manifesto["fontes_audio_bruto"]["gritos_reais_clipes"] = (
            real_info["treino"]["clipes"] + real_info["teste"]["clipes"])
    MANIFESTO.write_text(json.dumps(manifesto, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"MANIFESTO.json: {MANIFESTO}")

    linhas = [
        "# Resumo dos dados (gerado por manifesto.py)",
        "",
        f"Gerado em {manifesto['gerado_em']} em {manifesto['maquina']}.",
        "",
        "## Contagens",
        "",
        "| item | valor |",
        "|---|---|",
    ]
    for k, v in contagens.items():
        linhas.append(f"| {k} | {v} |")
    linhas += ["", "## Horas por categoria (streaming 80 ms)", "",
               "| categoria | treino (h) | avaliacao (h) |", "|---|---|---|"]
    for k, v in horas.items():
        linhas.append(f"| {k} | {v.get('treino', 0.0):.2f} | {v['avaliacao']:.2f} |")
    linhas += ["", "## Arquivos de features", "", "| arquivo | categoria | split | shape | dtype | horas |",
               "|---|---|---|---|---|---|"]
    for a in arquivos:
        if "chunks" in a and a["nome"].endswith("_features.npy"):
            linhas.append(f"| {a['nome']} | {a['categoria']} | {a['split']} | {a['shape']} | {a['dtype']} | {a['horas']:.2f} |")
        elif a["nome"].endswith(".npy") and "clipes" in a:
            linhas.append(f"| {a['nome']} | {a['categoria']} | {a['split']} | {a['shape']} | {a['dtype']} | {a['horas']:.2f} |")
    RESUMO.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    log(f"RESUMO.md: {RESUMO}")

    print(json.dumps(manifesto, indent=1, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
