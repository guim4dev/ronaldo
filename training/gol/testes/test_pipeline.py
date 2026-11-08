"""Provas do preparo de dados: features tem que bater com ronaldo/detector.py.

Roda com `uv run pytest -q` dentro de training/gol. Nao usa audio real baixado:
sintetiza um sinal deterministico e um "gol" com o piper quando disponivel.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

AQUI = Path(__file__).resolve().parent
GOL = AQUI.parent
REPO = GOL.parent.parent
sys.path.insert(0, str(GOL))
sys.path.insert(0, str(REPO))

import comum as C  # noqa: E402
import features as F  # noqa: E402


def audio_teste(segundos: float = 2.0, seed: int = 0) -> np.ndarray:
    """Sinal com fala-like: soma de harmonicos com envelope e ruido."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(segundos * C.SR)) / C.SR
    x = (
        0.35 * np.sin(2 * np.pi * 180 * t)
        + 0.20 * np.sin(2 * np.pi * 360 * t)
        + 0.10 * np.sin(2 * np.pi * 540 * t)
    )
    env = np.exp(-((t - segundos / 2) ** 2) / 0.05)
    x = x * env + rng.normal(0, 0.01, len(t))
    return np.clip(x, -1, 1).astype(np.float32)


def test_features_clip_tem_16_janelas() -> None:
    feats = F.features_clip(audio_teste(2.0))
    assert feats.shape == (16, F.DIM), feats.shape


def test_features_clip_igual_ao_detector() -> None:
    """A rota de clipe tem que ser identica a WakeWord._embed_clip."""
    from ronaldo.detector import WakeWord

    ex = F.extrator()
    audio16 = F._int16(audio_teste(2.0, seed=3))
    mels = ex.melspec(audio16)
    janelas = [mels[i : i + 76] for i in range(0, len(mels), 8) if len(mels[i : i + 76]) == 76]
    referencia = np.asarray(ex.embed(janelas))[-16:]
    nosso = F.features_clip(audio16.astype(np.float32) / 32767.0)
    assert nosso.shape == referencia.shape
    np.testing.assert_allclose(nosso, referencia, rtol=1e-5, atol=1e-5)


def test_streaming_igual_ao_detector(tmp_path: Path) -> None:
    """Streaming: mesma sequencia de 96 dimensoes que o detector produz por chunk."""
    from ronaldo.detector import WakeWord

    audio = audio_teste(2.0, seed=5)
    caminho = tmp_path / "a.wav"
    C.salvar_wav16(caminho, audio)
    # lote=1 = uma janela por chamada do embedding, igual ao detector
    nosso, rms = F.features_streaming(caminho, lote=1, dtype=np.float32)
    assert len(nosso) == len(rms) == int(2.0 * C.SR / F.CHUNK)

    det = WakeWord(REPO / "models" / "ronaldo_ptbr.onnx", REPO / "models")
    import soundfile as sf

    audio16, _ = sf.read(str(caminho), dtype="int16")  # o mesmo int16 que entrou no streaming
    linhas = []
    for i in range(len(audio16) // F.CHUNK):
        det.scores(audio16[i * F.CHUNK : (i + 1) * F.CHUNK])
        linhas.append(det._features[-1].copy())
    referencia = np.asarray(linhas, dtype=np.float32)
    assert referencia.shape == nosso.shape
    np.testing.assert_allclose(nosso, referencia, rtol=1e-6, atol=1e-6)
    # o arquivo salvo em float16 erra no maximo a quantizacao (~0.02 em 10)
    guardado, _ = F.features_streaming(caminho)
    assert guardado.dtype == np.float16
    assert np.abs(guardado.astype(np.float32) - referencia).max() < 0.02


def test_rms_em_dbfs() -> None:
    silencio = np.zeros(C.SR, dtype=np.float32)
    assert F.features_streaming_rms(silencio) < -100
    cheio = np.full(C.SR, 0.5, dtype=np.float32)
    r = F.features_streaming_rms(cheio)
    assert -6.5 < r < -5.5, r


def test_janela_posiciona_clip_no_fim() -> None:
    import random

    rng = random.Random(0)
    clip = audio_teste(0.5, seed=9)
    janela = C.janela_com_fundo(clip, None, rng)
    assert len(janela) == C.JANELA
    # o final da janela tem que ser o clipe; o comeco, o fundo baixo
    np.testing.assert_allclose(janela[-len(clip) :], clip / np.max(np.abs(clip)) * 0.95, atol=1e-4)
    assert np.abs(janela[: C.SR // 4]).max() < 0.01


def test_esticar_vogal_aumenta_duracao() -> None:
    x = audio_teste(0.6, seed=11)
    y = C.esticar_vogal(x, 2.0)
    assert len(y) > len(x) * 1.2


@pytest.mark.skipif(not (C.RAW / "piper" / "piper" / "piper").exists(), reason="piper nao baixado")
def test_piper_sintetiza() -> None:
    x = C.piper_texto("gol!", "cadu", 1.0, 0.7, 0.7)
    assert len(x) > C.SR // 4
    assert C.db_rms(x) > -40
