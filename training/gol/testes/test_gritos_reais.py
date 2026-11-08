"""Provas do conjunto de gritos humanos reais (roda com `uv run pytest -q`).

Se o split ainda nao foi gerado (clone novo, sem dados), o teste e pulado.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

AQUI = Path(__file__).resolve().parent
GOL = AQUI.parent
sys.path.insert(0, str(GOL))

import comum as C  # noqa: E402

SPLIT = C.FEATURES / "real_split.json"
META = C.RAW / "gritos" / "meta.jsonl"
CLIPS = C.RAW / "gritos" / "clips"

pytestmark = pytest.mark.skipif(
    not SPLIT.exists() or not META.exists(), reason="gritos reais nao gerados"
)

RE_GOL = re.compile(r"\bgo{1,}l{1,}\b|\bgo{1,}l+a[cç]o", re.I)


@pytest.fixture(scope="module")
def dados() -> tuple[dict, dict[str, dict]]:
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    meta = {
        m["clipe"]: m
        for m in (json.loads(l) for l in META.read_text(encoding="utf-8").splitlines() if l.strip())
        if m.get("clipe")
    }
    return split, meta


def test_split_nao_repete_video(dados) -> None:
    split, _ = dados
    treino = set(split["videos_treino"])
    teste = set(split["videos_teste"])
    assert not (treino & teste), sorted(treino & teste)[:10]
    # cada clipe listado pertence ao video do seu lado
    meta = {m["clipe"]: m for m in dados[1].values()}
    for lado, vids in (("treino", treino), ("teste", teste)):
        for nome in split[lado]:
            assert meta[nome]["video"] in vids, (lado, nome)


def test_todo_clipe_tem_transcricao_com_gol(dados) -> None:
    _, meta = dados
    for nome, m in meta.items():
        assert (CLIPS / nome).exists(), f"sumiu: {nome}"
        palavra = m.get("palavra") or ""
        texto = m.get("texto_clipe") or m.get("texto") or ""
        assert RE_GOL.search(palavra) or RE_GOL.search(texto), (nome, palavra, texto[:120])


def test_contagens_do_conjunto(dados) -> None:
    split, meta = dados
    assert len(split["treino"]) > 0, "treino vazio"
    assert len(split["teste"]) > 0, "teste vazio"
    assert len(split["videos_teste"]) > 0, "nenhum video de teste"
    assert len(split["videos_treino"]) > 0, "nenhum video de treino"
    # as listas do split cobrem exatamente os clipes do meta filtrado
    assert set(split["treino"]) | set(split["teste"]) <= set(meta)


def test_clipes_duram_no_maximo_3s(dados) -> None:
    _, meta = dados
    import soundfile as sf

    for nome in meta:
        info = sf.info(str(CLIPS / nome))
        dur = info.frames / info.samplerate
        assert 0.2 <= dur <= 3.01, (nome, dur)


def test_features_batem_com_os_clipes(dados) -> None:
    split, _ = dados
    treino = np.load(C.FEATURES / "real_train.npy", mmap_mode="r")
    teste = np.load(C.FEATURES / "real_test.npy", mmap_mode="r")
    assert treino.shape == (len(split["treino"]), 16, 96), treino.shape
    assert teste.shape == (len(split["teste"]), 16, 96), teste.shape
    assert str(treino.dtype) == "float16"
    assert str(teste.dtype) == "float16"
