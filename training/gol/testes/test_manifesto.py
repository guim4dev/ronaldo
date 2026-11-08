"""Confere o MANIFESTO.json contra o disco (roda com `uv run pytest -q`).

Se o manifesto nao existir (clone novo, sem dados), o teste e pulado: ele
existe para provar que o manifesto descreve o que esta em ~/data/gol.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

AQUI = Path(__file__).resolve().parent
GOL = AQUI.parent
REPO = GOL.parent.parent
sys.path.insert(0, str(GOL))

import comum as C  # noqa: E402

MANIFESTO = C.ROOT / "MANIFESTO.json"


pytestmark = pytest.mark.skipif(not MANIFESTO.exists(), reason="MANIFESTO.json nao gerado")


@pytest.fixture(scope="module")
def manifesto() -> dict:
    return json.loads(MANIFESTO.read_text(encoding="utf-8"))


def test_pipeline_declara_o_detector(manifesto: dict) -> None:
    assert "detector.py" in manifesto["pipeline"]["fonte_da_verdade"]
    assert manifesto["pipeline"]["embeddings_por_clipe"] == 16
    assert manifesto["pipeline"]["dim_embedding"] == 96


def test_toda_entrada_do_manifesto_existe_e_bate_a_forma(manifesto: dict) -> None:
    for arq in manifesto["arquivos"] + manifesto["externos"]:
        caminho = C.ROOT / arq["caminho"]
        assert caminho.exists(), f"sumiu: {caminho}"
        a = np.load(caminho, mmap_mode="r")
        assert list(a.shape) == arq["shape"], f"{caminho.name}: {a.shape} != {arq['shape']}"
        assert str(a.dtype) == arq["dtype"], f"{caminho.name}: {a.dtype} != {arq['dtype']}"


def test_curtos_tem_as_contagens_do_contrato(manifesto: dict) -> None:
    c = manifesto["contagens"]
    assert c["pos_train"] >= 19000, c["pos_train"]
    assert c["neg_train"] >= 19000, c["neg_train"]
    assert c["pos_test"] >= 900, c["pos_test"]
    assert c["frases_com_gol"] >= 300, c["frases_com_gol"]
    assert c["gritos_reais"] >= 60, c["gritos_reais"]


def test_avaliacao_longa_tem_8h_nas_tres_categorias(manifesto: dict) -> None:
    for nome in ("conversa", "jogo", "musica"):
        horas = manifesto["horas"][nome]
        assert horas["avaliacao"] >= 8.0, (nome, horas)
        assert horas["treino"] >= 8.0, (nome, horas)


def test_conversa_futebol_e_so_avaliacao(manifesto: dict) -> None:
    horas = manifesto["horas"]["conversa_futebol"]
    assert set(horas) == {"avaliacao"}, horas
    assert horas["avaliacao"] >= 4.0, horas
    meta = json.loads((C.FEATURES / "stream_conversa_futebol_avaliacao_meta.json").read_text())
    assert meta["so_avaliacao"] is True
    assert meta["categoria"] == "conversa_futebol"
    assert not list(C.FEATURES.glob("stream_conversa_futebol_treino*")), "nao pode haver treino"
    assert len(meta["arquivos"]) >= 1
    # mesmo pipeline: uma linha [96] por chunk de 80 ms
    assert meta["chunks"] > 0
    # horas e arredondada a 3 casas na conversao
    assert meta["horas"] == pytest.approx(meta["chunks"] * 0.08 / 3600.0, abs=0.0011)


def test_features_do_manifesto_sem_nan(manifesto: dict) -> None:
    for arq in manifesto["arquivos"]:
        if not arq["nome"].endswith(".npy") or "rms" in arq["nome"]:
            continue
        a = np.load(C.ROOT / arq["caminho"], mmap_mode="r")
        amostra = np.asarray(a[:500], dtype=np.float32)
        assert not np.isnan(amostra).any(), arq["nome"]
