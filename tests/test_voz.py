"""Modo voz: texto falável, cadeia de motores e o Falador de respostas."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
import wave
from pathlib import Path

import pytest
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.server import AsyncEventHandler, AsyncTcpServer
from wyoming.tts import Synthesize

from ronaldo import agent, listener, voz
from ronaldo.listener import Config, Listener, Route


# ---------------------------------------------------------------- essencial


def test_essencial_tira_markdown_codigo_url_emoji_e_link():
    texto = (
        "# Título\n\n"
        "**Negrito** e _itálico_ com `código` e [link](https://example.com/a).\n"
        "```python\nprint('oi')\n```\n"
        "Emoji 🚀 no fim."
    )
    assert voz.essencial(texto) == "Título Negrito e itálico com e link. Emoji no fim."


def test_essencial_troca_ronaldo_por_r_em_qualquer_caixa():
    assert voz.essencial("Ronaldo disse; RONALDO ouviu; ronaldo calou.") == "R. disse; R. ouviu; R. calou."


def test_essencial_tira_url_solta_e_citacao_markdown():
    assert voz.essencial("Antes https://example.com/a/b depois") == "Antes depois"
    assert voz.essencial("> citação") == "citação"


def test_essencial_tira_token_e_caminhos_longos():
    texto = "⟦c:abc123⟧ está em /home/ana/Projects/ronaldo e em src/ronaldo/agent.py."
    saida = voz.essencial(texto)
    assert "⟦" not in saida and "abc123" not in saida
    assert "/home" not in saida and "src/ronaldo" not in saida
    assert saida.startswith("está em")


def test_essencial_vazio():
    for texto in ("", "   \n\t", "```\ncode\n```", "⟦c:x⟧"):
        assert voz.essencial(texto) == ""


def test_essencial_pega_frases_inteiras_e_avisa_quando_corta():
    texto = "Primeira frase curta. Segunda frase também curta. Terceira frase que passa do limite."
    curto = voz.essencial(texto, limite=50)
    assert curto == "Primeira frase curta." + voz.AVISO
    assert len(curto) <= 50

    maior = voz.essencial(texto, limite=80)
    assert maior == "Primeira frase curta. Segunda frase também curta." + voz.AVISO
    assert len(maior) <= 80


def test_essencial_frase_unica_maior_que_o_limite_corta_palavra_inteira():
    saida = voz.essencial("palavra " * 100, limite=40)
    assert saida.endswith(voz.AVISO)
    assert len(saida) <= 40
    assert "palavr " not in saida


def test_essencial_nao_quebra_a_inicial_r():
    assert voz.essencial("Ronaldo disse. R. Silva respondeu.") == "R. disse. R. Silva respondeu."


# ---------------------------------------------------------------- estado e comandos


def test_estado_ligado_desligado_no_arquivo(tmp_path):
    estado = tmp_path / "modo-voz.json"
    assert voz.ligado(estado) is False
    voz.ligar(estado)
    assert voz.ligado(estado) is True
    assert json.loads(estado.read_text()) == {"ligado": True}
    voz.desligar(estado)
    assert voz.ligado(estado) is False


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Modo voz", "ligar"),
        ("RONALDO, liga o modo voz.", "ligar"),
        ("ligar modo voz", "ligar"),
        ("modo texto", "desligar"),
        ("Ronaldo, desliga o modo voz!", "desligar"),
        ("desligar modo voz", "desligar"),
        ("qual o modo voz do ronaldo", None),
        ("modo voz agora mesmo por favor", None),
        ("", None),
        # variações reais e frases parecidas que não são comando
        ("Ligar modo TTS", "ligar"),
        ("Ronaldo, liga o modo fala.", "ligar"),
        ("ativar modo tts", "ligar"),
        ("Liga a voz", "ligar"),
        ("modo fala", "ligar"),
        ("desligar modo TTS", "desligar"),
        ("desliga o modo fala", "desligar"),
        ("desativar modo voz", "desligar"),
        ("Desliga a voz!", "desligar"),
        ("O modo fala tá ligado?", None),  # pergunta, não comando: vai pro agente
        ("liga a voz do agente agora por favor", None),  # mais de 5 palavras
        ("modo tts é bom", None),
    ],
)
def test_comando_modo(texto, esperado):
    assert voz.comando_modo(texto) == esperado


# ---------------------------------------------------------------- config


def test_config_padrao_e_arquivo(tmp_path):
    cfg = voz.VozConfig.load(tmp_path / "nao-existe.toml")
    assert cfg.motores == ["say:Luciana"]
    assert cfg.volume == 0.3
    assert cfg.enviar == [] and cfg.resposta == []
    assert cfg.enviado == "Enviado."
    assert cfg.ligado == "As respostas vão ser faladas."

    arquivo = tmp_path / "config.toml"
    arquivo.write_text(
        '[voz]\n'
        'motores = ["wyoming://servidor:10201#voz-a", "say:Faber"]\n'
        'volume = 0.15\n'
        'enviar = ["/mock/agente", "ask", "--id", "{id}", "--json", "--", "{text}"]\n'
        'resposta = ["/mock/agente", "status", "--canal", "{canal}", "{id}", "--json"]\n'
        'enviado = "Enviado ({canal})."\n'
        'ligado = "As respostas vão ser faladas."\n'
    )
    cfg = voz.VozConfig.load(arquivo)
    assert cfg.motores == ["wyoming://servidor:10201#voz-a", "say:Faber"]
    assert cfg.volume == 0.15
    assert cfg.enviar == ["/mock/agente", "ask", "--id", "{id}", "--json", "--", "{text}"]
    assert cfg.resposta == ["/mock/agente", "status", "--canal", "{canal}", "{id}", "--json"]
    assert cfg.enviado == "Enviado ({canal})."
    assert cfg.ligado == "As respostas vão ser faladas."


def test_config_ignora_campos_invalidos(tmp_path):
    arquivo = tmp_path / "config.toml"
    arquivo.write_text('[voz]\nenviar = "nao-e-lista"\nresposta = []\nenviado = 3\nligado = "  "\nvolume = true\n')
    cfg = voz.VozConfig.load(arquivo)
    assert cfg.enviar == [] and cfg.resposta == []
    assert cfg.enviado == "Enviado."
    assert cfg.ligado == "As respostas vão ser faladas."
    assert cfg.volume == 0.3


# ---------------------------------------------------------------- motores


class FakePlayer:
    epoca = 0

    def __init__(self, tocar=True):
        self.plays = []
        self.tocar = tocar

    def play(self, caminho, volume, epoca=None):
        self.plays.append((str(caminho), volume))
        return self.tocar

    def run(self, argv, *, timeout=None, epoca=None):
        return 1

    def stop(self):
        pass


class RecordingPlayer:
    def __init__(self):
        self.calls = []

    def run(self, argv, *, timeout=None, epoca=None):
        self.calls.append((argv, timeout))
        if argv[0] == "say":
            Path(argv[argv.index("-o") + 1]).write_bytes(b"x")
        return 0


def test_say_usa_a_voz_e_a_velocidade_pedidas(tmp_path):
    player = RecordingPlayer()
    caminho = voz._sintetizar_say("oi", "Luciana", 4.0, player)
    argv, timeout = player.calls[0]
    assert argv[:6] == ["say", "-v", "Luciana", "-r", "190", "-o"]
    assert argv[-1] == "oi"
    assert timeout == 4.0
    assert Path(caminho).exists()
    os.unlink(caminho)


def test_player_toca_com_o_volume_pedido(monkeypatch):
    player = voz.Player()
    chamadas = []
    monkeypatch.setattr(player, "run", lambda argv, timeout=None, epoca=None: chamadas.append(argv) or 0)
    assert player.play("a.wav", 0.15)
    assert chamadas == [["afplay", "-v", "0.15", "a.wav"]]


def test_parse_wyoming_aceita_voz_com_dois_pontos():
    assert voz._parse_wyoming("wyoming://servidor:10201#kokoro:voz-a") == ("servidor", 10201, "kokoro:voz-a")


def test_cadeia_pula_motor_que_falha_ou_estoura(monkeypatch, tmp_path):
    ordem = []
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    def wyoming(texto, host, porta, nome, timeout):
        ordem.append(("wyoming", host, porta, nome))
        raise TimeoutError("demorou")

    def say(texto, nome, timeout, player, epoca=None):
        ordem.append(("say", nome))
        return str(audio)

    monkeypatch.setattr(voz, "_sintetizar_wyoming", wyoming)
    monkeypatch.setattr(voz, "_sintetizar_say", say)
    player = FakePlayer()

    assert voz.falar_texto(
        "oi",
        motores=["wyoming://servidor:10201#kokoro:voz-a", "say:Luciana"],
        volume=0.2,
        player=player,
    )
    assert ordem == [("wyoming", "servidor", 10201, "kokoro:voz-a"), ("say", "Luciana")]
    assert player.plays == [(str(audio), 0.2)]
    assert not audio.exists()  # temporário apagado depois de tocar


def test_cadeia_usa_say_quando_wyoming_devolve_none(monkeypatch, tmp_path):
    ordem = []
    audio = tmp_path / "a.aiff"
    audio.write_bytes(b"x")
    monkeypatch.setattr(voz, "_sintetizar_wyoming", lambda *a, **k: ordem.append("wyoming") or None)
    monkeypatch.setattr(voz, "_sintetizar_say", lambda *a, **k: ordem.append("say") or str(audio))
    player = FakePlayer()

    assert voz.falar_texto("oi", motores=["wyoming://h:1#v", "say:Luciana"], player=player)
    assert ordem == ["wyoming", "say"]
    assert len(player.plays) == 1


def test_cadeia_devolve_falso_quando_todos_falham(monkeypatch):
    monkeypatch.setattr(voz, "_sintetizar_wyoming", lambda *a, **k: None)
    monkeypatch.setattr(voz, "_sintetizar_say", lambda *a, **k: None)
    player = FakePlayer()
    assert voz.falar_texto("oi", motores=["wyoming://h:1#v", "say:Luciana"], player=player) is False
    assert player.plays == []


def test_cadeia_ignora_motor_desconhecido():
    assert voz.falar_texto("oi", motores=["motor-estranho"], player=FakePlayer()) is False


class FakeWyoming(AsyncEventHandler):
    def __init__(self, reader, writer, recebidos):
        super().__init__(reader, writer)
        self.recebidos = recebidos

    async def handle_event(self, event):
        if not Synthesize.is_type(event.type):
            return True
        sintese = Synthesize.from_event(event)
        self.recebidos.append(sintese)
        await self.write_event(AudioStart(rate=16000, width=2, channels=1).event())
        await self.write_event(AudioChunk(rate=16000, width=2, channels=1, audio=b"\x01\x00" * 32).event())
        await self.write_event(AudioStop().event())
        return False


class WyomingServer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.ready = threading.Event()
        self.recebidos = []
        self.loop = None
        self.server = None

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.server = AsyncTcpServer("127.0.0.1", 0)
        self.loop.run_until_complete(self.server.start(lambda r, w: FakeWyoming(r, w, self.recebidos)))
        self.port = self.server._server.sockets[0].getsockname()[1]
        self.ready.set()
        self.loop.run_forever()

    def close(self):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.join(2)


def test_cliente_wyoming_sintetiza_com_servidor_falso():
    servidor = WyomingServer()
    servidor.start()
    assert servidor.ready.wait(5)
    caminho = None
    try:
        caminho = voz._sintetizar_wyoming("olá mundo", "127.0.0.1", servidor.port, "kokoro:voz-a", timeout=3)
        assert caminho
        with wave.open(caminho) as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
            assert wav.getnframes() == 32
        assert servidor.recebidos[0].text == "olá mundo"
        assert servidor.recebidos[0].voice.name == "kokoro:voz-a"
    finally:
        if caminho:
            os.unlink(caminho)
        servidor.close()


def _esperar(condicao, timeout=2.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.01)
    return False


def test_player_mata_o_processo_atual():
    player = voz.Player()
    inicio = time.monotonic()
    resultado = {}

    def tocar():
        resultado["rc"] = player.run(["/bin/sleep", "10"])

    thread = threading.Thread(target=tocar)
    thread.start()
    assert _esperar(lambda: player._proc is not None)
    player.stop()
    thread.join(3)
    assert not thread.is_alive()
    assert time.monotonic() - inicio < 3
    assert resultado["rc"] != 0


# ---------------------------------------------------------------- falador


def _falador(tmp_path, respostas, falas, *, quando=None, **kwargs):
    estado = tmp_path / "estado.json"
    voz.ligar(estado)
    consultas = []

    def consultar(id, contexto):
        consultas.append((id, contexto))
        return respostas[id]

    def falar(texto, em=None):
        falas.append(texto)
        return True

    f = voz.Falador(
        consultar=consultar,
        falar=falar,
        estado=estado,
        falados=tmp_path / "falados.json",
        automatico=False,
        **kwargs,
    )
    f.consultas = consultas
    return f


def test_falador_so_fala_pronta_com_texto(tmp_path):
    respostas = {
        "a": {"estado": "aguardando", "texto": "", "em": None},
        "b": {"estado": "respondendo", "texto": "parcial", "em": 1.0},
        "c": {"estado": "sem_fala", "texto": "", "em": None},
        "d": {"estado": "pronta", "texto": "   ", "em": 2.0},
    }
    falas = []
    f = _falador(tmp_path, respostas, falas)
    for id in respostas:
        f.enfileirar(id, {"canal": "casa"})
    f.passo()
    assert falas == []


def test_falador_fala_na_ordem_em_que_ficam_prontas(tmp_path):
    respostas = {
        "a": {"estado": "aguardando", "texto": "", "em": None},
        "b": {"estado": "aguardando", "texto": "", "em": None},
    }
    falas = []
    f = _falador(tmp_path, respostas, falas)
    f.enfileirar("a", {"canal": "casa"})
    f.enfileirar("b", {"canal": "casa"})

    respostas["b"] = {"estado": "pronta", "texto": "B primeiro", "em": 1.0}
    f.passo()
    respostas["a"] = {"estado": "pronta", "texto": "A depois", "em": 2.0}
    f.passo()
    assert falas == ["B primeiro", "A depois"]


def test_falador_varias_prontas_no_mesmo_ciclo_seguem_a_fila(tmp_path):
    respostas = {
        "a": {"estado": "pronta", "texto": "A", "em": 1.0},
        "b": {"estado": "pronta", "texto": "B", "em": 1.0},
    }
    falas = []
    f = _falador(tmp_path, respostas, falas)
    f.enfileirar("a", {"canal": "casa"})
    f.enfileirar("b", {"canal": "casa"})
    f.passo()
    assert falas == ["A", "B"]


def test_falador_nao_repete_nem_depois_de_reiniciar(tmp_path):
    respostas = {"a": {"estado": "pronta", "texto": "uma vez", "em": 1.0}}
    falas = []
    f = _falador(tmp_path, respostas, falas)
    f.enfileirar("a", {"canal": "casa"})
    f.passo()
    assert falas == ["uma vez"]

    respostas["a"] = {"estado": "pronta", "texto": "de novo", "em": 2.0}
    f.passo()
    assert falas == ["uma vez"]

    falas2 = []
    f2 = _falador(tmp_path, respostas, falas2)
    assert f2.enfileirar("a", {"canal": "casa"}) is False
    f2.passo()
    assert falas2 == []


def test_falador_descarta_item_vencido(tmp_path):
    respostas = {"a": {"estado": "pronta", "texto": "tarde", "em": 1.0}}
    falas = []
    f = _falador(tmp_path, respostas, falas, relogio=lambda: 100.0, prazo=10.0)
    f.enfileirar("a", {"canal": "casa"}, quando=0.0)
    f.passo()
    assert f.pendentes() == []
    assert f.consultas == []
    assert falas == []


def test_falador_nao_fala_enquanto_grava(tmp_path):
    respostas = {"a": {"estado": "pronta", "texto": "espera", "em": 1.0}}
    falas = []
    f = _falador(tmp_path, respostas, falas)
    f.enfileirar("a", {"canal": "casa"})
    voz.marcar_gravando(True)
    try:
        f.passo()
    finally:
        voz.marcar_gravando(False)
    assert falas == [] and f.consultas == []
    f.passo()
    assert falas == ["espera"]


def test_falador_parar_mata_o_audio_e_nao_repete(tmp_path):
    respostas = {"a": {"estado": "pronta", "texto": "longa", "em": 1.0}}
    estado = tmp_path / "estado.json"
    voz.ligar(estado)
    comecou = threading.Event()

    def falar(texto, em=None):
        comecou.set()
        f.player.run(["/bin/sleep", "10"])
        return False

    f = voz.Falador(
        consultar=lambda id, contexto: respostas[id],
        falar=falar,
        estado=estado,
        falados=tmp_path / "falados.json",
        automatico=False,
    )
    f.enfileirar("a", {"canal": "casa"}, quando=f.relogio())
    thread = threading.Thread(target=f.passo)
    thread.start()
    assert comecou.wait(2)
    assert _esperar(lambda: f.player._proc is not None)
    inicio = time.monotonic()
    f.parar()
    thread.join(3)
    assert not thread.is_alive()
    assert time.monotonic() - inicio < 3
    assert f.ja_falado("a")

    falas = []
    f2 = voz.Falador(
        consultar=lambda id, contexto: respostas[id],
        falar=lambda texto, em=None: falas.append(texto) or True,
        estado=estado,
        falados=tmp_path / "falados.json",
        automatico=False,
    )
    assert f2.enfileirar("a", {"canal": "casa"}) is False
    f2.passo()
    assert falas == []


def test_falador_usa_o_proprio_player_e_parar_mata(tmp_path, monkeypatch):
    chamadas = []

    def fake_falar_texto(texto, *, motores=None, volume=None, player=None, epoca=None):
        chamadas.append((texto, player))
        player.run(["/bin/sleep", "10"])
        return False

    monkeypatch.setattr(voz, "falar_texto", fake_falar_texto)
    estado = tmp_path / "estado.json"
    voz.ligar(estado)
    f = voz.Falador(estado=estado, falados=tmp_path / "falados.json", automatico=False)
    thread = threading.Thread(target=f.falar_agora, args=("oi",))
    thread.start()
    limite = time.monotonic() + 2
    while time.monotonic() < limite and not chamadas:
        time.sleep(0.02)
    assert chamadas and chamadas[0][1] is f.player
    assert _esperar(lambda: f.player._proc is not None)
    inicio = time.monotonic()
    f.parar()
    thread.join(3)
    assert not thread.is_alive()
    assert time.monotonic() - inicio < 3


def test_falador_desligado_para_a_fala_e_esvazia_a_fila(tmp_path):
    respostas = {
        "a": {"estado": "pronta", "texto": "atual", "em": 1.0},
        "b": {"estado": "aguardando", "texto": "", "em": None},
    }
    estado = tmp_path / "estado.json"
    voz.ligar(estado)
    comecou = threading.Event()

    def falar(texto, em=None):
        comecou.set()
        f.player.run(["/bin/sleep", "10"])
        return False

    f = voz.Falador(
        consultar=lambda id, contexto: respostas[id],
        falar=falar,
        estado=estado,
        falados=tmp_path / "falados.json",
        intervalo=0.05,
        automatico=True,
    )
    try:
        f.enfileirar("a", {"canal": "casa"}, quando=f.relogio())
        f.enfileirar("b", {"canal": "casa"}, quando=f.relogio())
        assert comecou.wait(3)
        voz.desligar(estado)
        limite = time.monotonic() + 3
        while time.monotonic() < limite and (not f.ja_falado("a") or f.pendentes()):
            time.sleep(0.05)
        assert f.ja_falado("a")
        assert f.pendentes() == []
    finally:
        f._parar_thread.set()
        f._thread.join(1)
        f._vigia.join(1)


def test_falador_gravando_impede_nova_fala(tmp_path):
    respostas = {"a": {"estado": "pronta", "texto": "A", "em": 1.0}}
    falas = []
    f = _falador(tmp_path, respostas, falas, gravando_fn=lambda: True)
    f.enfileirar("a", {"canal": "casa"})
    f.passo()
    assert falas == []


# ---------------------------------------------------------------- agent e listener


def _proc(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


def _config_voz(tmp_path, monkeypatch, *, enviar=None, resposta=None, enviado="Enviado."):
    enviar = enviar or ["/mock/agente", "ask", "--id", "{id}", "--json", "--", "{text}"]
    resposta = resposta or ["/mock/agente", "status", "--canal", "{canal}", "{id}", "--json"]
    arquivo = tmp_path / "config.toml"
    arquivo.write_text(
        "[voz]\n"
        f"enviar = {json.dumps(enviar)}\n"
        f"resposta = {json.dumps(resposta)}\n"
        f"enviado = {json.dumps(enviado)}\n"
    )
    monkeypatch.setattr(voz, "CONFIG", arquivo)
    return arquivo


def test_agent_modo_voz_liga_fala_e_nao_chama_o_envio(monkeypatch):
    chamadas = []
    monkeypatch.setattr(voz, "ligar", lambda: chamadas.append("ligar"))
    monkeypatch.setattr(voz, "falar_agora", lambda texto: chamadas.append(("falar", texto)) or True)

    def proibido(*args, **kwargs):
        raise AssertionError("não devia chamar o envio")

    monkeypatch.setattr(agent.subprocess, "run", proibido)
    ok, reply = agent.run(
        ["/mock/agente", "ask", "{text}"],
        "Ronaldo, liga o modo voz!",
        path="/bin",
        timeout=10,
        notify_reply=False,
        name="agente",
        voz=True,
    )
    assert ok and reply == "Modo voz ligado."
    assert chamadas == ["ligar", ("falar", "Modo voz ligado.")]


def test_agent_modo_texto_desliga_sem_falar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(voz, "desligar", lambda: chamadas.append("desligar"))
    monkeypatch.setattr(voz, "falar_agora", lambda texto: chamadas.append(("falar", texto)) or True)
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: pytest.fail("não devia chamar o envio"))
    ok, reply = agent.run(
        ["/mock/agente", "ask", "{text}"],
        "modo texto",
        path="/bin",
        timeout=10,
        notify_reply=False,
        name="agente",
        voz=True,
    )
    assert ok and reply == "Modo texto."
    assert chamadas == ["desligar"]


def test_agent_sem_rota_de_voz_ignora_os_comandos(monkeypatch):
    chamadas = []

    def fake_run(argv, **kwargs):
        chamadas.append(argv)
        return _proc(0, "ok")

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    ok, _ = agent.run(
        ["/mock/agente", "ask", "{text}"],
        "modo voz",
        path="/bin",
        timeout=10,
        notify_reply=False,
        name="agente",
        voz=False,
    )
    assert ok
    assert chamadas == [["/mock/agente", "ask", "modo voz"]]


def test_agent_modo_desligado_mantem_o_comando_de_hoje(monkeypatch):
    chamadas = []
    monkeypatch.setattr(voz, "ligado", lambda: False)

    def fake_run(argv, **kwargs):
        chamadas.append(argv)
        return _proc(0, "ok")

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    ok, _ = agent.run(
        ["/mock/agente", "ask", "{text}"],
        "pergunta",
        path="/bin",
        timeout=10,
        notify_reply=False,
        name="agente",
        voz=True,
    )
    assert ok
    assert chamadas == [["/mock/agente", "ask", "pergunta"]]


def test_agent_modo_voz_ligado_monta_argv_e_enfileira(tmp_path, monkeypatch):
    _config_voz(tmp_path, monkeypatch, enviado="Enviado ({canal}).")
    chamadas = []
    monkeypatch.setattr(voz, "ligado", lambda: True)
    monkeypatch.setattr(voz, "enfileirar", lambda id, contexto, quando=None: chamadas.append((id, contexto)) or True)

    def fake_run(argv, **kwargs):
        chamadas.append(list(argv))
        return _proc(0, json.dumps({"ok": True, "canal": "casa"}))

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    ok, reply = agent.run(
        ["/mock/agente", "ask", "{text}"],
        "qual é a boa?",
        path="/bin",
        timeout=10,
        notify_reply=False,
        name="agente",
        voz=True,
    )
    argv = chamadas[0]
    oid = argv[argv.index("--id") + 1]
    assert argv == ["/mock/agente", "ask", "--id", oid, "--json", "--", "qual é a boa?"]
    assert len(oid) == 32 and int(oid, 16) >= 0
    assert chamadas[1] == (oid, {"id": oid, "canal": "casa"})
    assert ok and reply == "Enviado (casa)."


def test_agent_envio_sem_texto_manda_pelo_stdin(tmp_path, monkeypatch):
    _config_voz(tmp_path, monkeypatch, enviar=["/mock/agente", "ask", "--id", "{id}", "--json"])
    visto = {}
    monkeypatch.setattr(voz, "ligado", lambda: True)
    monkeypatch.setattr(voz, "enfileirar", lambda *a, **k: True)

    def fake_run(argv, **kwargs):
        visto["argv"] = argv
        visto["input"] = kwargs.get("input")
        return _proc(0, json.dumps({"ok": True, "canal": "casa"}))

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    assert agent.run(["/mock/agente"], "no stdin", path="/bin", timeout=10, notify_reply=False, name="agente", voz=True)[0]
    assert visto["argv"][:3] == ["/mock/agente", "ask", "--id"]
    assert visto["input"] == "no stdin"


def test_atalho_continua_vencendo_o_modo_voz(monkeypatch):
    enfileirados = []
    monkeypatch.setattr(voz, "ligado", lambda: True)
    monkeypatch.setattr(voz, "enfileirar", lambda *a, **k: enfileirados.append(a) or True)
    monkeypatch.setattr("ronaldo.atalhos.executar_comando", lambda *a, **k: ("entregue", "Tocou musica."))
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: pytest.fail("não devia chamar o envio"))
    ok, reply = agent.run(
        ["/mock/agente", "ask", "{text}"],
        "musica",
        path="/bin",
        timeout=10,
        notify_reply=False,
        name="agente",
        voz=True,
        atalhos=[{"palavras": ["musica"], "comando": ["/mock/tocador"], "nome": "musica"}],
    )
    assert ok and "Tocou" in reply
    assert enfileirados == []


def test_agent_envio_falhando_nao_enfileira(tmp_path, monkeypatch):
    _config_voz(tmp_path, monkeypatch)
    enfileirados = []
    monkeypatch.setattr(voz, "ligado", lambda: True)
    monkeypatch.setattr(voz, "enfileirar", lambda *a, **k: enfileirados.append(a) or True)
    monkeypatch.setattr(
        agent.subprocess,
        "run",
        lambda *a, **k: _proc(1, json.dumps({"ok": False, "error": {"message": "sem canal"}})),
    )
    ok, reply = agent.run(
        ["/mock/agente", "ask", "{text}"],
        "pergunta",
        path="/bin",
        timeout=10,
        notify_reply=False,
        name="agente",
        voz=True,
    )
    assert ok is False and "sem canal" in reply
    assert enfileirados == []


def test_agent_placeholder_faltando_na_resposta_falha_no_envio(tmp_path, monkeypatch):
    _config_voz(tmp_path, monkeypatch)
    enfileirados = []
    monkeypatch.setattr(voz, "ligado", lambda: True)
    monkeypatch.setattr(voz, "enfileirar", lambda *a, **k: enfileirados.append(a) or True)
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: _proc(0, json.dumps({"ok": True})))
    ok, reply = agent.run(
        ["/mock/agente", "ask", "{text}"],
        "pergunta",
        path="/bin",
        timeout=10,
        notify_reply=False,
        name="agente",
        voz=True,
    )
    assert ok is False
    assert "canal" in reply and "não devolveu" in reply
    assert enfileirados == []


def test_listener_para_fala_e_marca_gravacao(monkeypatch):
    eventos = []
    monkeypatch.setattr(listener.voz, "parar", lambda: eventos.append("parar"))
    monkeypatch.setattr(listener.voz, "marcar_gravando", lambda valor: eventos.append(("gravando", valor)))
    monkeypatch.setattr(listener.hexcli, "ensure_running", lambda: False)
    instancia = Listener.__new__(Listener)
    instancia.cfg = Config(routes=[Route(model="x", action="command", command=["/mock/agente"], hud=False)])
    instancia.path = "/bin"
    instancia._dictate(instancia.cfg.routes[0])
    assert eventos == ["parar", ("gravando", True), ("gravando", False)]


def test_listener_manda_voz_para_o_agente(monkeypatch):
    recebido = []
    monkeypatch.setattr(listener.hexcli, "ensure_running", lambda: True)
    monkeypatch.setattr(listener.hexcli, "ensure_language", lambda lang: True)
    monkeypatch.setattr(listener.hexcli, "start_dictation", lambda: True)
    monkeypatch.setattr(listener.hexcli, "stop_and_transcribe", lambda: "pergunta")
    monkeypatch.setattr(listener.agent, "dispatch", lambda template, text, **kw: recebido.append(kw))
    monkeypatch.setattr(listener.voz, "parar", lambda: None)
    monkeypatch.setattr(listener.voz, "marcar_gravando", lambda valor: None)
    instancia = Listener.__new__(Listener)
    instancia.cfg = Config(routes=[Route(model="x", action="command", command=["/mock/agente"], voz=True)])
    instancia.path = "/bin"
    instancia._record_until_silence = lambda: "silence"
    instancia._dictate(instancia.cfg.routes[0])
    assert recebido and recebido[0]["voz"] is True


def test_rota_voz_so_existe_em_command():
    with pytest.raises(ValueError, match="voz"):
        Route(model="x", action="type", voz=True)
    rota = Route(model="x", action="command", command=["/mock/agente"], voz=True)
    assert rota.voz is True


def test_config_le_a_secao_voz_sem_avisar(tmp_path):
    arquivo = tmp_path / "c.toml"
    arquivo.write_text(
        '[[routes]]\nmodel="x"\naction="command"\ncommand=["/mock/agente"]\nvoz=true\n'
        '[voz]\nvolume=0.2\n'
        'enviar=["/mock/agente","ask","{text}"]\n'
        'resposta=["/mock/agente","status","{id}"]\n'
    )
    cfg = Config.load(arquivo)
    assert cfg.routes[0].voz is True
    assert cfg.voz == {
        "volume": 0.2,
        "enviar": ["/mock/agente", "ask", "{text}"],
        "resposta": ["/mock/agente", "status", "{id}"],
    }


# ---------------------------------------------------------------- config do modo voz


def test_consultar_resposta_usa_placeholders_do_config(tmp_path, monkeypatch):
    _config_voz(tmp_path, monkeypatch)
    visto = {}

    def fake_run(argv, **kw):
        visto["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout='{"estado": "pronta", "texto": "oi", "em": 1.0}', stderr="")

    monkeypatch.setattr(voz.subprocess, "run", fake_run)
    assert voz.consultar_resposta("a" * 32, {"canal": "casa"}, path="/bin")["texto"] == "oi"
    assert visto["argv"] == ["/mock/agente", "status", "--canal", "casa", "a" * 32, "--json"]


def test_consultar_resposta_sem_campo_do_contexto_falha(tmp_path, monkeypatch):
    _config_voz(tmp_path, monkeypatch)
    monkeypatch.setattr(voz.subprocess, "run", lambda *a, **k: pytest.fail("não devia rodar"))
    with pytest.raises(RuntimeError, match=r"\{canal\}"):
        voz.consultar_resposta("a" * 32, {}, path="/bin")


def test_consultar_resposta_sem_config_falha(tmp_path, monkeypatch):
    monkeypatch.setattr(voz, "CONFIG", tmp_path / "nao-existe.toml")
    with pytest.raises(RuntimeError, match=r"\[voz\]\.resposta"):
        voz.consultar_resposta("a" * 32, {}, path="/bin")


# ---------------------------------------------------------------- CLI


def test_cli_on_off_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(voz, "ESTADO", tmp_path / "modo-voz.json")
    assert voz.main(["status"]) == 0
    assert capsys.readouterr().out.strip() == "desligado"
    assert voz.main(["on"]) == 0
    assert capsys.readouterr().out.strip() == "Modo voz ligado."
    assert voz.ligado() is True
    assert voz.main(["status"]) == 0
    assert capsys.readouterr().out.strip() == "ligado"
    assert voz.main(["off"]) == 0
    assert capsys.readouterr().out.strip() == "Modo texto."
    assert voz.ligado() is False


def test_cli_falar_usa_o_motor(monkeypatch):
    falado = []
    monkeypatch.setattr(voz, "falar_texto", lambda texto, **kw: falado.append(texto) or True)
    assert voz.main(["falar", "bom", "dia"]) == 0
    assert falado == ["bom dia"]


def test_cli_uso_invalido(capsys):
    assert voz.main([]) == 2
    assert voz.main(["nada"]) == 2
    assert "uso" in capsys.readouterr().err


def test_parar_durante_sintese_wyoming_nao_toca(monkeypatch, tmp_path):
    """Regressão: parar() durante a síntese (sem processo de áudio ainda) não pode deixar o áudio tocar."""
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    liberar = threading.Event()
    sintetizando = threading.Event()

    def sintese_bloqueada(*a, **k):
        sintetizando.set()
        liberar.wait(5)
        return str(audio)

    monkeypatch.setattr(voz, "_sintetizar_wyoming", sintese_bloqueada)
    monkeypatch.setattr(voz, "_apagar", lambda c: None)
    player = voz.Player()
    tocados = []
    monkeypatch.setattr(player, "run", lambda argv, timeout=None, epoca=None: tocados.append(argv) or 0)
    resultado = {}
    t = threading.Thread(target=lambda: resultado.setdefault("ok", voz.falar_texto(
        "oi", motores=["wyoming://h:1#v", "say:Luciana"], volume=0.1, player=player)))
    t.start()
    assert sintetizando.wait(2)
    player.stop()  # o que a wake word / desligar fazem
    liberar.set()
    t.join(3)
    assert resultado["ok"] is False
    assert tocados == []  # nem afplay, nem fallback say


def test_falador_parar_entre_checagem_e_fala_nao_toca(tmp_path, monkeypatch):
    """parar() logo depois do Falador escolher o item: a época capturada sob o lock cancela a fala."""
    estado = tmp_path / "estado.json"
    voz.ligar(estado)
    tocou = []
    f = voz.Falador(
        consultar=lambda id, contexto: {"estado": "pronta", "texto": "resposta", "em": 1.0},
        estado=estado, falados=tmp_path / "falados.json", automatico=False,
        ligado_fn=lambda: True, gravando_fn=lambda: False,
    )
    monkeypatch.setattr(f.player, "run", lambda argv, timeout=None, epoca=None: tocou.append(argv) or 0)
    original = f._falar_pronto

    def com_parar(item, texto, em, cancelar):
        f.player.stop()  # parar() chega antes do falar_texto começar
        return original(item, texto, em, cancelar)

    monkeypatch.setattr(f, "_falar_pronto", com_parar)
    monkeypatch.setattr(voz, "_sintetizar_say", lambda *a, **k: str(tmp_path / "x.aiff"))
    f.enfileirar("a" * 32, {})
    f.passo()
    assert tocou == []
    assert f.ja_falado("a" * 32)
