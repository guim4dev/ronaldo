"""Portão de grito: nível, referência, recalibragem e log — tudo em memória."""

import logging

import numpy as np
import pytest

from ronaldo.detector import CHUNK
from ronaldo.grito import PASSO, SILENCIO_DB, PortaoGrito, rms_dbfs


def chunk_db(db: float) -> np.ndarray:
    """Chunk constante cujo RMS fica em `db` dBFS."""
    amplitude = int(round(32768 * 10 ** (db / 20)))
    return np.full(CHUNK, amplitude, dtype=np.int16)


def test_rms_dbfs_de_um_chunk_constante():
    assert rms_dbfs(chunk_db(-6)) == pytest.approx(-6, abs=0.1)
    assert rms_dbfs(np.zeros(CHUNK, dtype=np.int16)) == SILENCIO_DB


def test_nivel_e_o_pico_dos_ultimos_13_chunks():
    portao = PortaoGrito()
    for _ in range(13):
        portao.observar(chunk_db(-40), True)
    assert portao.nivel == pytest.approx(-40, abs=0.1)

    portao.observar(chunk_db(-20), True)
    assert portao.nivel == pytest.approx(-20, abs=0.1)

    for _ in range(13):
        portao.observar(chunk_db(-40), True)
    assert portao.nivel == pytest.approx(-40, abs=0.1)


def test_sem_20s_de_fala_nao_ha_referencia_nem_disparo():
    portao = PortaoGrito()
    for _ in range(249):  # 19,92 s
        portao.observar(chunk_db(-30), True)
    assert portao.referencia is None
    assert portao.avaliar(0.9, 10).liberado is False

    portao.observar(chunk_db(-30), True)  # 20,0 s
    assert portao.referencia == pytest.approx(-30, abs=0.2)
    portao.observar(chunk_db(-15), True)  # +15 dB no nível, referência na fala normal
    assert portao.avaliar(0.9, 10).liberado is True


def test_referencia_usa_so_fala_e_ignora_silencio():
    portao = PortaoGrito()
    for _ in range(250):
        portao.observar(chunk_db(-30), True)
    for _ in range(200):
        portao.observar(np.zeros(CHUNK, dtype=np.int16), False)
    assert portao.referencia == pytest.approx(-30, abs=0.3)


def test_grito_precisa_de_10_db_acima_da_referencia():
    portao = PortaoGrito()
    for _ in range(250):
        portao.observar(chunk_db(-30), True)
    for _ in range(13):
        portao.observar(chunk_db(-25), True)
    decisao = portao.avaliar(0.9, 10)
    assert decisao.liberado is False
    assert decisao.referencia == pytest.approx(-30, abs=0.3)

    for _ in range(13):
        portao.observar(chunk_db(-15), True)
    assert portao.avaliar(0.9, 10).liberado is True


def test_desvio_de_ganho_invalida_e_exige_20s_de_fala_nova(caplog):
    portao = PortaoGrito()
    for _ in range(250):
        portao.observar(chunk_db(-30), True)
    assert portao.referencia is not None

    with caplog.at_level(logging.INFO, logger="ronaldo.grito"):
        for _ in range(70):  # +12 dB de ganho: a janela de 10 s já é maioria nova
            portao.observar(chunk_db(-18), True)
    assert "referência de grito recalibrando" in caplog.text
    assert portao.referencia is None
    assert portao.fala_acumulada == pytest.approx(7 * PASSO)  # só a fala depois da invalidação

    for _ in range(250):  # 20 s de fala no nível novo
        portao.observar(chunk_db(-18), True)
    assert portao.referencia == pytest.approx(-18, abs=0.3)


def test_log_do_candidato_traz_nota_nivel_referencia_e_decisao(caplog):
    portao = PortaoGrito()
    for _ in range(250):
        portao.observar(chunk_db(-30), True)
    with caplog.at_level(logging.INFO, logger="ronaldo.grito"):
        portao.avaliar(0.77, 10)
    texto = caplog.text
    assert "nota 0.77" in texto
    assert "-30.0 dB" in texto
    assert "liberado=False" in texto


def test_silencio_total_nao_quebra_a_referencia():
    portao = PortaoGrito()
    for _ in range(250):
        portao.observar(chunk_db(-30), True)
    for _ in range(125):
        portao.observar(np.zeros(CHUNK, dtype=np.int16), False)
    assert portao.referencia == pytest.approx(-30, abs=0.3)
    assert portao.nivel == SILENCIO_DB
