"""Provas do treino e da avaliacao do gol_grito (sem dados reais baixados).

Roda com `uv run pytest -q` dentro de training/gol.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

AQUI = Path(__file__).resolve().parent
GOL = AQUI.parent
REPO = GOL.parent.parent
sys.path.insert(0, str(GOL))
sys.path.insert(0, str(REPO))

import modelo as M  # noqa: E402


# --------------------------------------------------------------------------- #
# unidades
# --------------------------------------------------------------------------- #
def test_chunk_nivel_tem_o_rms_pedido() -> None:
    for db in (-40.0, -26.0, -14.0, -3.0):
        chunk = M.chunk_nivel(db)
        assert chunk.dtype == np.int16 and len(chunk) == M.CHUNK
        amostras = chunk.astype(np.float64) / 32768.0
        rms = float(np.sqrt(np.mean(amostras * amostras)))
        assert abs(20 * math.log10(rms) - db) < 0.01, db


def _validar_pessoal(saida: Path | None, dados: Path | None = None) -> subprocess.CompletedProcess[str]:
    comando = [sys.executable, str(GOL / "train.py"), "--pessoal"]
    if saida is not None:
        comando += ["--saida", str(saida)]
    if dados is not None:
        comando += ["--pessoal-dados", str(dados)]
    return subprocess.run(comando, capture_output=True, text=True, timeout=30)


def test_pessoal_exige_saida() -> None:
    r = _validar_pessoal(None)
    assert r.returncode != 0
    assert "--pessoal exige --saida explícito" in r.stderr


def test_pessoal_recusa_saida_dentro_do_repo(tmp_path: Path) -> None:
    r = _validar_pessoal(REPO / "training" / "gol" / "nao-criar.onnx")
    assert r.returncode != 0
    assert "fora de qualquer worktree Git" in r.stderr
    assert not (REPO / "training" / "gol" / "nao-criar.onnx").exists()


def test_pessoal_recusa_saida_dentro_de_git() -> None:
    r = _validar_pessoal(REPO / ".git" / "nao-criar.onnx")
    assert r.returncode != 0
    assert "caminhos .git" in r.stderr


def test_pessoal_falha_fechado_se_rev_parse_falhar(tmp_path: Path, monkeypatch) -> None:
    import train as T

    def falha(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, "", "fatal: permission denied")

    monkeypatch.setattr(T.subprocess, "run", falha)
    with pytest.raises(SystemExit, match="nao foi possivel validar.*Git"):
        T._caminho_fora_de_git(tmp_path / "modelo.onnx", "--saida")


def test_gravar_modelo_revalida_destino_pessoal(tmp_path: Path) -> None:
    import train as T

    with pytest.raises(SystemExit, match="fora de qualquer worktree Git"):
        T.gravar_modelo(None, REPO / "training" / "gol" / "nao-criar.onnx", pessoal=True)
    assert not (REPO / "training" / "gol" / "nao-criar.onnx").exists()


def test_pessoal_recusa_symlink_externo_para_dentro_do_repo(tmp_path: Path) -> None:
    link = tmp_path / "saida.onnx"
    link.symlink_to(REPO / "README.md")
    r = _validar_pessoal(link)
    assert r.returncode != 0
    assert "fora de qualquer worktree Git" in r.stderr


def test_pessoal_recusa_models_mesmo_fora_do_repo(tmp_path: Path) -> None:
    r = _validar_pessoal(tmp_path / "models" / "gol_grito.onnx")
    assert r.returncode != 0
    assert "fora de qualquer pasta models/" in r.stderr


def test_pessoal_aceita_saida_e_dados_fora_de_git(tmp_path: Path) -> None:
    import train as T

    fora = tmp_path / "privado"
    T.validar_caminhos_pessoais(fora / "modelo.onnx", fora / "audio")


def test_pessoal_recusa_dados_dentro_do_repo(tmp_path: Path) -> None:
    r = _validar_pessoal(tmp_path / "modelo.onnx", REPO / "training" / "gol" / "audio")
    assert r.returncode != 0
    assert "--pessoal-dados deve ficar fora de qualquer worktree Git" in r.stderr


def test_repo_nao_rastreia_arquivos_de_audio() -> None:
    r = subprocess.run(["git", "-C", str(REPO), "ls-files"], check=True,
                       capture_output=True, text=True)
    extensoes = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".opus", ".aac"}
    audios = [p for p in r.stdout.splitlines() if Path(p).suffix.lower() in extensoes]
    assert not audios, f"arquivos de áudio rastreados: {audios}"


def test_limite_poisson_zero_alarmes() -> None:
    # 0 alarmes em 16 h -> ~3/T = 0,1875/h (o limite que o relatorio cita)
    assert abs(M.limite_poisson(0, 16.0) - 3.0 / 16.0) < 1e-9
    assert M.limite_poisson(0, 11.0) > M.limite_poisson(3, 11.0) / 3


def test_contar_disparos_respeita_8s() -> None:
    indices = np.arange(0, 500, dtype=np.int64)
    scores = np.zeros(500, dtype=np.float32)
    scores[[10, 50, 120, 230, 460]] = 0.9  # 50 esta a 40 chunks (3,2 s) do 10
    disparos = M.contar_disparos(indices, scores, 0.5)
    assert disparos == [10, 120, 230, 460]


def test_portao_releases_grito_e_barra_fala() -> None:
    PortaoGrito = M.carregar_portao()
    portao = M.preparar_portao(PortaoGrito)
    assert portao.referencia is not None
    # grito: referencia + 12 dB; acima do limiar de 10 dB
    assert M.portao_libera_grito(portao, 0.9)
    # fala normal no nivel da referencia: barrada (portao novo, sem o pico do grito)
    portao_fala = M.preparar_portao(PortaoGrito)
    assert not M.portao_libera_fala(portao_fala, 0.9)


def test_segmentos_do_meta(tmp_path: Path) -> None:
    import soundfile as sf

    dados = tmp_path / "gol"
    pasta = dados / "raw" / "game" / "wav"
    pasta.mkdir(parents=True)
    nomes = ["a.wav", "b.wav"]
    for nome, chunks in zip(nomes, (50, 30)):
        sf.write(str(pasta / nome), np.zeros(chunks * M.CHUNK, np.int16), M.SR, subtype="PCM_16")
    meta = {"chunks": 80, "arquivos": nomes}
    segmentos = M.segmentos_do_meta(meta, dados, "game")
    assert segmentos == [(0, 50), (50, 80)]
    # arquivo faltando: cai para um segmento unico
    meta2 = {"chunks": 80, "arquivos": nomes + ["sumiu.wav"]}
    assert M.segmentos_do_meta(meta2, dados, "game") == [(0, 80)]


def test_alinhamento_monta_janelas_da_producao() -> None:
    import train as T

    # dois clipes de 40 chunks; palavra [20,30) e [25,35) em chunks
    stream = np.random.default_rng(0).normal(0, 0.2, (80, 96)).astype(np.float16)
    offsets = np.asarray([0, 40, 80], dtype=np.int64)
    meta = {"itens": [
        {"chunks": 40, "inicio_chunk": 20.0, "fim_chunk": 30.0},
        {"chunks": 40, "inicio_chunk": 25.0, "fim_chunk": 35.0},
    ]}
    al = T.PositivosAlinhados(stream, offsets, meta, val_frac=0.5, seed=0)
    pos0 = al.positivas[0]
    neg0 = al.negativas[0]
    # fim da palavra em 2,4 s: positivas de k=29 (fim) a k=35 (fim+0,48 s)
    assert pos0 == list(range(29, 36)), pos0
    # antes da palavra: k=15..18
    assert neg0 == [15, 16, 17, 18], neg0
    pos1 = al.positivas[1]
    assert pos1 == list(range(34, 40)), pos1
    # amostra: 25% de janelas negativas, o resto positivo
    x, y = al.amostrar(200, np.random.default_rng(1), frac_neg=0.25)
    assert x.shape == (200, 16, 96) and y.shape == (200,)
    assert set(np.unique(y)) <= {0.0, 1.0}
    assert 0.1 < float(np.mean(y == 0)) < 0.45


def test_iter_janelas_nao_cruza_segmento() -> None:
    feats = np.arange(100 * 96, dtype=np.float16).reshape(100, 96)
    indices, janelas = [], []
    for a, bloco in M.iter_janelas(feats, [(0, 40), (40, 100)], lote=7):
        indices.append(np.arange(a, a + len(bloco)))
        janelas.append(bloco)
    indices = np.concatenate(indices)
    janelas = np.concatenate(janelas)
    assert len(indices) == len(janelas) == (40 - 15) + (60 - 15)
    for i, janela in zip(indices, janelas):
        # a janela termina em i e comeca em i-15, sem atravessar a fronteira 40
        assert janela[0, 0] == feats[i - 15, 0]
        assert janela[-1, 0] == feats[i, 0]
        assert i - 15 >= 0 and (i < 40 or i - 15 >= 40)


# --------------------------------------------------------------------------- #
# fumaca de ponta a ponta (treino + export + WakeWord)
# --------------------------------------------------------------------------- #
def test_treino_smoke_exporta_e_wakeword_carrega(tmp_path: Path) -> None:
    import soundfile as sf

    pytest.importorskip("torch")
    rng = np.random.default_rng(1)
    dados = tmp_path / "gol"
    feat = dados / "features"
    oww = dados / "raw" / "openwakeword"
    for pasta in (feat, oww):
        pasta.mkdir(parents=True)

    n, dim, jan = 64, M.DIM, M.JANELA
    np.save(feat / "pos_train.npy", (rng.normal(0, 0.3, (n, jan, dim)) + 1.0).astype(np.float16))
    np.save(feat / "neg_train.npy", rng.normal(0, 0.3, (n, jan, dim)).astype(np.float16))
    np.save(oww / "openwakeword_features_ACAV100M_2000_hrs_16bit.npy",
            rng.normal(0, 0.3, (2000, jan, dim)).astype(np.float16))
    np.save(oww / "validation_set_features.npy", rng.normal(0, 0.3, (300, dim)).astype(np.float16))

    for categoria in ("speech_ptbr", "game", "music"):
        pasta = dados / "raw" / categoria / "wav"
        pasta.mkdir(parents=True)
        chunks = 200
        sf.write(str(pasta / "a.wav"), np.zeros(chunks * M.CHUNK, np.int16), M.SR, subtype="PCM_16")
        np.save(feat / f"stream_{categoria}_treino_features.npy",
                rng.normal(0, 0.3, (chunks, dim)).astype(np.float16))
        np.save(feat / f"stream_{categoria}_treino_rms.npy", np.full(chunks, -30.0, np.float32))
        meta = {"arquivo_features": f"features/stream_{categoria}_treino_features.npy",
                "arquivo_rms": f"features/stream_{categoria}_treino_rms.npy",
                "chunks": chunks, "horas": round(chunks * 0.08 / 3600, 3),
                "arquivos": ["a.wav"]}
        (feat / f"stream_{categoria}_treino_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    saida = tmp_path / "gol_grito.onnx"
    comando = [
        sys.executable, str(GOL / "train.py"), "--smoke",
        "--dados", str(dados), "--saida", str(saida),
        "--epocas", "1", "--passos-por-epoca", "2",
        "--lote-pos", "8", "--lote-neg", "8", "--lote-acav", "16", "--lote-stream", "3",
        "--threads", "1",
    ]
    r = subprocess.run(comando, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert saida.exists() and saida.stat().st_size > 50_000

    sys.path.insert(0, str(REPO))
    from ronaldo.detector import WakeWord

    modelo = WakeWord(saida, REPO / "models")
    audio = (rng.normal(0, 0.02, M.SR * 2) * 32768).astype(np.int16)
    notas = [
        modelo.scores(audio[i : i + M.CHUNK])[saida.stem]
        for i in range(0, len(audio) - M.CHUNK + 1, M.CHUNK)
    ]
    assert all(0.0 <= n <= 1.0 for n in notas)
