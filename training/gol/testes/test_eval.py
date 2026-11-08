from __future__ import annotations

import math
import sys
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

GOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOL))

import eval as E  # noqa: E402
import train as T  # noqa: E402


def _resultado(limiares: list[float], acertos: list[int], fa_conversa: list[float],
               fa_jogo_musica: list[float]) -> dict:
    return {
        "clipes": {"real_teste": {
            "clipes": 10,
            "por_limiar": {
                limiar: {"com": {"acertos": n}}
                for limiar, n in zip(limiares, acertos)
            },
        }},
        "conversa": {"por_limiar": {
            limiar: {"com": {"fa_h": fa}}
            for limiar, fa in zip(limiares, fa_conversa)
        }},
        "jogo_musica": {"por_limiar": {
            limiar: {"com": {"fa_h": fa}}
            for limiar, fa in zip(limiares, fa_jogo_musica)
        }},
    }


def test_escolher_limiar_maximiza_acerto_sob_metas_de_fa() -> None:
    limiares = [0.3, 0.4, 0.5]
    resultado = _resultado(limiares, [7, 9, 10], [0.5, 0.2, 0.1], [0.2, 0.15, 0.21])
    escolha = E.escolher_limiar(resultado, limiares)
    assert escolha["escolhido"]["limiar"] == 0.4
    assert escolha["meta_fa_atingida"] is True


def test_escolher_limiar_usa_maior_grade_se_fa_nao_bater() -> None:
    limiares = [0.3, 0.4, 0.5]
    resultado = _resultado(limiares, [10, 8, 4], [1.0, 0.8, 0.6], [0.8, 0.7, 0.4])
    escolha = E.escolher_limiar(resultado, limiares)
    assert escolha["escolhido"]["limiar"] == 0.5
    assert escolha["meta_fa_atingida"] is False


def test_split_real_por_video_nao_separa_clipes_do_mesmo_video() -> None:
    nomes = ["video-a_00.wav", "video-a_01.wav", "video-b_00.wav", "video-c_00.wav"]
    treino, validacao = T._split_real_por_video(nomes, ["video-a", "video-b", "video-c"], 0.34, 7)
    assert set(treino).isdisjoint(validacao)
    assert (0 in treino) == (1 in treino)
    assert (0 in validacao) == (1 in validacao)


def test_intervalo_wilson_cobre_taxa_observada_e_limites() -> None:
    baixo, alto = E.intervalo_wilson(10, 17)
    assert baixo < 10 / 17 < alto
    assert E.intervalo_wilson(0, 17)[0] == 0.0
    assert E.intervalo_wilson(17, 17)[1] == 1.0
    assert all(math.isnan(x) for x in E.intervalo_wilson(0, 0))


def test_real_test_avalia_janelas_de_16_embeddings(tmp_path: Path) -> None:
    class Sessao:
        def get_inputs(self):
            return [SimpleNamespace(name="input", shape=[1, 16, 96])]

        def run(self, outputs, feed):
            janela = feed["input"]
            assert janela.shape == (1, 16, 96)
            return [np.asarray([[float(janela.mean())]], dtype=np.float32)]

    caminho = tmp_path / "real_test.npy"
    np.save(caminho, np.stack([
        np.zeros((16, 96), dtype=np.float16),
        np.full((16, 96), 0.8, dtype=np.float16),
    ]))
    resultado = E.avaliar_features_curtas(Sessao(), caminho, [0.5], None)
    assert resultado["clipes"] == 2
    assert resultado["por_limiar"][0.5]["com"]["acertos"] == 1
    assert resultado["por_limiar"][0.5]["com"]["ic95_wilson"]
