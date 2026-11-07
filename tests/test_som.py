"""Rota `som`: portão de grito, intervalo em tempo de áudio e serialização."""

from __future__ import annotations

import os
import shlex
import subprocess
import time

import numpy as np
import pytest

from ronaldo import agent, hexcli, som as som_mod
from ronaldo import voz
from ronaldo.detector import CHUNK, SAMPLE_RATE
from ronaldo.listener import Config, Listener, Route

PASSO = CHUNK / SAMPLE_RATE


def onda(segundos: float, amplitude: float = 1200.0, ganho_db: float = 0.0) -> np.ndarray:
    """Fala sintética (seno 440 Hz) com um ganho global."""
    n = int(round(segundos * SAMPLE_RATE))
    t = np.arange(n) / SAMPLE_RATE
    sinal = amplitude * 10 ** (ganho_db / 20) * np.sin(2 * np.pi * 440 * t)
    return np.clip(np.round(sinal), -32768, 32767).astype(np.int16)


def pedacos(audio: np.ndarray):
    return [audio[i : i + CHUNK] for i in range(0, len(audio) - CHUNK + 1, CHUNK)]


class FakeVad:
    def speech_prob(self, chunk, frame: int = 640) -> float:
        x = np.asarray(chunk, dtype=np.float64) / 32768
        return 0.9 if float(np.sqrt(np.mean(x * x))) > 1e-4 else 0.0

    def reset(self) -> None:
        pass


class FakeWake:
    """Notas altas só nos índices (0-based) combinados; conta resets."""

    def __init__(self, nomes, disparos=None):
        self.nomes = list(nomes)
        self.disparos = {nome: set(ids) for nome, ids in (disparos or {}).items()}
        self.i = -1
        self.resets = 0

    def scores(self, chunk):
        self.i += 1
        return {nome: 0.9 if self.i in self.disparos.get(nome, set()) else 0.0 for nome in self.nomes}

    def reset(self) -> None:
        self.resets += 1


class FakeSom:
    def __init__(self, eventos=None):
        self.tocados: list[list[str]] = []
        self.paradas = 0
        self._tocando = False
        self.eventos = eventos

    def tocar(self, argv, *, path=som_mod.PATH_PADRAO, nome="som"):
        self.tocados.append(list(argv))
        self._tocando = True
        return True

    def tocando(self):
        return self._tocando

    def stop(self):
        self.paradas += 1
        self._tocando = False
        if self.eventos is not None:
            self.eventos.append("som.stop")


def criar_listener(monkeypatch, routes, wake, som_player=None):
    monkeypatch.setattr("ronaldo.agent.login_path", lambda: "/usr/bin:/bin")
    return Listener(Config(routes=routes), wake=wake, vad=FakeVad(), som_player=som_player or FakeSom())


def alimentar(listener, audio):
    for chunk in pedacos(audio):
        listener.processar_chunk(chunk)


def rota_som(**kwargs):
    dados = dict(model="gol.onnx", action="som", command=["/usr/bin/afplay", "gol.wav"], threshold=0.6)
    dados.update(kwargs)
    return Route(**dados)


# ---------------------------------------------------------------- disparo e intervalo


def test_som_dispara_uma_vez(monkeypatch):
    player = FakeSom()
    wake = FakeWake(["gol"], {"gol": {388, 392, 396}})
    listener = criar_listener(monkeypatch, [rota_som()], wake, player)

    alimentar(listener, np.concatenate([onda(30), onda(2, ganho_db=12)]))

    assert player.tocados == [["/usr/bin/afplay", "gol.wav"]]


def test_som_respeita_intervalo_de_8s_em_tempo_de_audio(monkeypatch):
    player = FakeSom()
    # primeiro disparo no chunk 388; 487 fica a 99 chunks (7,92 s) e 488 a 100 (8,0 s)
    wake = FakeWake(["gol"], {"gol": {388, 487, 488}})
    listener = criar_listener(monkeypatch, [rota_som()], wake, player)

    alimentar(listener, np.concatenate([
        onda(30),                # 0..374
        onda(2, ganho_db=12),    # 375..399
        onda(6),                 # 400..474
        onda(1.2, ganho_db=12),  # 475..489
    ]))

    assert len(player.tocados) == 2
    assert listener._ultimo_som["gol"] == 489  # chunk 488 (0-based) + 1


@pytest.mark.parametrize("ganho", [-12.0, 0.0, 12.0])
def test_sem_referencia_nenhum_ganho_dispara(monkeypatch, ganho):
    player = FakeSom()
    wake = FakeWake(["gol"], {"gol": {138}})
    listener = criar_listener(monkeypatch, [rota_som()], wake, player)

    alimentar(listener, np.concatenate([onda(10, ganho_db=ganho), onda(2, ganho_db=ganho + 12)]))

    assert listener.grito.referencia is None
    assert player.tocados == []


def test_com_referencia_so_o_grito_passa(monkeypatch):
    player = FakeSom()
    # 390: fala normal no mesmo nível da referência (barrada); 413: grito +12 dB
    wake = FakeWake(["gol"], {"gol": {390, 413}})
    listener = criar_listener(monkeypatch, [rota_som()], wake, player)

    alimentar(listener, np.concatenate([onda(30), onda(2), onda(2, ganho_db=12)]))

    assert len(player.tocados) == 1
    assert listener._ultimo_som["gol"] == 414


def test_troca_de_ganho_invalida_e_exige_20s_de_fala_nova(monkeypatch):
    player = FakeSom()
    wake = FakeWake(["gol"], {"gol": {445, 460, 650, 703}})
    listener = criar_listener(monkeypatch, [rota_som()], wake, player)

    alimentar(listener, onda(30))                              # calibra em 0 dB
    assert listener.grito.referencia is not None
    alimentar(listener, onda(10, ganho_db=12))                 # ganho novo: invalida
    assert listener.grito.referencia is None
    assert player.tocados == []                                # candidatos 445/460 barrados

    alimentar(listener, onda(16, ganho_db=12))                 # completa 20 s de fala nova
    assert listener.grito.referencia is not None
    assert player.tocados == []                                # 650 era fala normal

    alimentar(listener, onda(2, ganho_db=24))                  # grito +12 dB acima do novo normal
    assert len(player.tocados) == 1
    assert listener._ultimo_som["gol"] == 704


# ---------------------------------------------------------------- serialização


def test_ditado_para_o_som_antes_do_hex(monkeypatch):
    eventos = []
    player = FakeSom(eventos=eventos)
    rota_fala = Route(model="ronaldo.onnx", action="type")
    listener = criar_listener(monkeypatch, [rota_som(), rota_fala], FakeWake(["gol", "ronaldo"]), player)
    monkeypatch.setattr(hexcli, "ensure_running", lambda: eventos.append("hex") or False)
    monkeypatch.setattr(voz, "parar", lambda: eventos.append("voz.parar"))
    monkeypatch.setattr(voz, "marcar_gravando", lambda valor: eventos.append(("gravando", valor)))

    listener._dictate(rota_fala)

    assert eventos.index("som.stop") < eventos.index("hex")
    assert eventos[:2] == ["som.stop", "voz.parar"]


def test_falador_espera_o_som_acabar(tmp_path, monkeypatch):
    voz.marcar_gravando(False)
    tocando = {"valor": True}
    monkeypatch.setattr(voz.som_mod, "tocando", lambda: tocando["valor"])
    estado = tmp_path / "estado.json"
    voz.ligar(estado)
    falas = []
    falador = voz.Falador(
        consultar=lambda id, reino: {"estado": "pronta", "texto": "resposta", "em": 1.0},
        falar=lambda texto, em=None: falas.append(texto) or True,
        estado=estado,
        falados=tmp_path / "falados.json",
        automatico=False,
    )
    falador.enfileirar("pessoal", "a" * 32)

    falador.passo()
    assert falas == []

    tocando["valor"] = False
    falador.passo()
    assert falas == ["resposta"]


def test_som_durante_fala_nao_para_a_fala(monkeypatch):
    player = FakeSom()
    wake = FakeWake(["gol"], {"gol": {388}})
    listener = criar_listener(monkeypatch, [rota_som()], wake, player)
    eventos = []
    monkeypatch.setattr(voz, "parar", lambda: eventos.append("parar"))
    monkeypatch.setattr(voz, "marcar_gravando", lambda valor: eventos.append(("gravando", valor)))

    alimentar(listener, np.concatenate([onda(30), onda(2, ganho_db=12)]))

    assert len(player.tocados) == 1
    assert eventos == []  # nada de voz.parar/marcar_gravando
    assert wake.resets == 0  # o WakeWord não foi resetado pelo disparo


# ---------------------------------------------------------------- rotas e config


def test_rota_command_carregada_junto_continua_funcionando(monkeypatch):
    rota_cmd = Route(model="ronaldo.onnx", action="command", command=["agente", "{text}"], hud=False)
    wake = FakeWake(["gol", "ronaldo"], {"ronaldo": {0}})
    listener = criar_listener(monkeypatch, [rota_som(), rota_cmd], wake)
    monkeypatch.setattr(hexcli, "ensure_running", lambda: True)
    monkeypatch.setattr(hexcli, "ensure_language", lambda lang: True)
    monkeypatch.setattr(hexcli, "start_dictation", lambda: True)
    monkeypatch.setattr(hexcli, "stop_and_transcribe", lambda: "abre o PR")
    monkeypatch.setattr(voz, "parar", lambda: None)
    monkeypatch.setattr(voz, "marcar_gravando", lambda valor: None)
    listener._record_until_silence = lambda: "silence"
    enviados = []
    monkeypatch.setattr(agent, "dispatch", lambda template, text, **kw: enviados.append((template, text)))

    rota = listener.processar_chunk(onda(PASSO)[:CHUNK])
    assert rota is rota_cmd
    listener._dictate(rota)
    assert enviados == [(["agente", "{text}"], "abre o PR")]


def test_config_som_le_os_campos(tmp_path):
    arquivo = tmp_path / "c.toml"
    arquivo.write_text(
        '[[routes]]\nmodel="gol.onnx"\naction="som"\ncommand=["/usr/bin/afplay","a.wav"]\n'
        "intervalo_seconds=12\ngrito_db_acima=14\n"
    )
    rota = Config.load(arquivo).routes[0]
    assert rota.intervalo_seconds == 12.0
    assert rota.grito_db_acima == 14.0


def test_config_som_sem_command_falha(tmp_path):
    arquivo = tmp_path / "c.toml"
    arquivo.write_text('[[routes]]\nmodel="gol.onnx"\naction="som"\n')
    with pytest.raises(ValueError, match="command"):
        Config.load(arquivo)


def test_som_player_expande_til_e_nao_espera(monkeypatch):
    chamadas = []

    class Proc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(argv, **kwargs):
        chamadas.append((argv, kwargs))
        return Proc()

    monkeypatch.setattr(som_mod.subprocess, "Popen", fake_popen)
    player = som_mod.SomPlayer()
    assert player.tocar(["/usr/bin/afplay", "-v", "0.6", "~/Music/Reino/gol.wav"], nome="gol")
    argv, kwargs = chamadas[0]
    assert argv[3] == os.path.expanduser("~/Music/Reino/gol.wav")
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert player.tocando() is True
    player.stop()
    assert player.tocando() is False


def test_som_de_ponta_a_ponta_com_comando_real(tmp_path, monkeypatch):
    """Portão + SomPlayer de verdade: o comando roda sem bloquear a escuta."""
    alvo = tmp_path / "tocou"
    player = som_mod.SomPlayer()
    wake = FakeWake(["gol"], {"gol": {388}})
    listener = criar_listener(
        monkeypatch,
        [rota_som(command=["/bin/sh", "-c", f"printf gol > {shlex.quote(str(alvo))}"])],
        wake,
        player,
    )

    alimentar(listener, np.concatenate([onda(30), onda(2, ganho_db=12)]))

    limite = time.monotonic() + 3
    while time.monotonic() < limite and not alvo.exists():
        time.sleep(0.02)
    player.stop()
    assert alvo.read_text() == "gol"
