"""Cancel state, the global shortcut, the HUD contract and the listener paths."""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from ronaldo import cancelar, ctl, hexcli, hotkey, hud, listener, voz
from ronaldo.listener import Config, Listener, Route


# ---------------------------------------------------------------- helpers


def _listener() -> Listener:
    instancia = Listener.__new__(Listener)
    instancia.cfg = Config(routes=[])
    instancia.path = "/usr/bin:/bin"
    instancia.vad = SimpleNamespace(reset=lambda: None, speech_prob=lambda chunk: 0.0)
    return instancia


def _preparar_hex(monkeypatch, eventos: list, texto: str = "texto") -> None:
    monkeypatch.setattr(listener.hexcli, "ensure_running", lambda: True)
    monkeypatch.setattr(listener.hexcli, "ensure_language", lambda lang: True)
    monkeypatch.setattr(listener.hexcli, "start_dictation", lambda: eventos.append("start") or True)
    monkeypatch.setattr(listener.hexcli, "stop_and_transcribe", lambda: eventos.append("stop") or texto)
    monkeypatch.setattr(listener.hexcli, "discard_dictation", lambda: eventos.append("discard"))
    monkeypatch.setattr(listener.agent, "dispatch", lambda *a, **k: eventos.append("dispatch"))
    monkeypatch.setattr(listener.macos, "type_and_submit", lambda *a, **k: eventos.append("type"))
    monkeypatch.setattr(listener.voz, "parar", lambda: None)


def _huds(monkeypatch) -> list:
    mostrados = []
    monkeypatch.setattr(listener.agent_hud, "begin", lambda: 1)
    monkeypatch.setattr(listener.agent_hud, "show", lambda *a, **k: mostrados.append((a, k)))
    return mostrados


class _Proc:
    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass


# ---------------------------------------------------------------- atalho


def test_parse_aceita_modificadores_e_teclas():
    assert hotkey.parse("cmd+d") == (hotkey.CMD, 2)
    assert hotkey.parse("command+d") == (hotkey.CMD, 2)
    assert hotkey.parse("shift+cmd+.") == (hotkey.CMD | hotkey.SHIFT, 47)
    assert hotkey.parse("ctrl+alt+d") == (hotkey.CTRL | hotkey.ALT, 2)
    assert hotkey.parse("option+command+escape") == (hotkey.CMD | hotkey.ALT, 53)
    assert hotkey.parse("escape") == (0, 53)
    assert hotkey.parse(" CMD + D ") == (hotkey.CMD, 2)
    assert hotkey.parse("cmd+,") == (hotkey.CMD, 43)


@pytest.mark.parametrize(
    "atalho", ["", "   ", "cmd", "cmd+", "+d", "cmd+naoexiste", "cmd+d+e", "hiper+d"]
)
def test_parse_recusa_atalhos_invalidos(atalho):
    assert hotkey.parse(atalho) is None


def test_rotulo_do_atalho():
    assert hotkey.rotulo("cmd+d") == "⌘D"
    assert hotkey.rotulo("cmd+.") == "⌘."
    assert hotkey.rotulo("shift+cmd+d") == "⇧⌘D"
    assert hotkey.rotulo("escape") == "Esc"
    assert hotkey.rotulo("cmd+space") == "⌘Space"
    assert hotkey.rotulo("") == ""
    assert hotkey.rotulo("cmd+naoexiste") == ""


def test_iniciar_fora_do_macos_nao_falha(monkeypatch):
    monkeypatch.setattr(hotkey.sys, "platform", "linux")
    hotkey.iniciar("cmd+d", lambda: None, lambda: False)


def test_atalho_invalido_nao_instala_tap(monkeypatch):
    monkeypatch.setattr(hotkey.sys, "platform", "darwin")
    chamadas = []
    monkeypatch.setattr(hotkey, "_instalar", lambda *a: chamadas.append(a))
    hotkey.iniciar("cmd+naoexiste", lambda: None, lambda: False)
    assert chamadas == []


def test_tecla_configurada_engole_o_evento():
    pedidos = []
    estado = {
        "alvo": (hotkey.CMD, 2),
        "pedir": lambda: pedidos.append("pedir"),
        "ativo": lambda: True,
        "dentro": lambda x, y: False,
    }
    assert hotkey._tratar(hotkey.KEY_DOWN, 2, hotkey.CMD, None, estado) is True
    assert hotkey._tratar(hotkey.KEY_UP, 2, hotkey.CMD, None, estado) is True
    # a different modifier set is not the configured shortcut
    assert hotkey._tratar(hotkey.KEY_DOWN, 2, hotkey.CMD | hotkey.SHIFT, None, estado) is False
    assert pedidos == ["pedir", "pedir"]


def test_tecla_fora_do_atalho_passa_direto():
    pedidos = []
    estado = {
        "alvo": (hotkey.CMD, 2),
        "pedir": lambda: pedidos.append("pedir"),
        "ativo": lambda: True,
        "dentro": lambda x, y: False,
    }
    assert hotkey._tratar(hotkey.KEY_DOWN, 3, hotkey.CMD, None, estado) is False
    assert hotkey._tratar(hotkey.KEY_DOWN, 2, 0, None, estado) is False
    assert pedidos == []


def test_escape_sem_modificador_nao_engole_cmd_escape():
    pedidos = []
    estado = {
        "alvo": (0, 53),
        "pedir": lambda: pedidos.append("pedir"),
        "ativo": lambda: True,
        "dentro": lambda x, y: False,
    }
    assert hotkey._tratar(hotkey.KEY_DOWN, 53, 0, None, estado) is True
    assert hotkey._tratar(hotkey.KEY_DOWN, 53, hotkey.CMD, None, estado) is False
    assert pedidos == ["pedir"]


def test_atalho_inativo_nao_engole():
    pedidos = []
    estado = {
        "alvo": (hotkey.CMD, 2),
        "pedir": lambda: pedidos.append("pedir"),
        "ativo": lambda: False,
        "dentro": lambda x, y: True,
    }
    assert hotkey._tratar(hotkey.KEY_DOWN, 2, hotkey.CMD, None, estado) is False
    assert hotkey._tratar(hotkey.MOUSE_DOWN, None, 0, (1, 2), estado) is False
    assert pedidos == []


def test_clique_na_pilula_engole_e_clique_fora_passa():
    pedidos = []
    estado = {
        "alvo": (hotkey.CMD, 2),
        "pedir": lambda: pedidos.append("pedir"),
        "ativo": lambda: True,
        "dentro": lambda x, y: (x, y) == (10, 20),
    }
    assert hotkey._tratar(hotkey.MOUSE_DOWN, None, 0, (10, 20), estado) is True
    assert hotkey._tratar(hotkey.MOUSE_UP, None, 0, (0, 0), estado) is False
    assert pedidos == ["pedir"]


def test_tap_desabilitado_se_reativa():
    chamadas = []
    estado = {
        "cg": SimpleNamespace(CGEventTapEnable=lambda tap, ligado: chamadas.append((tap, ligado))),
        "tap": "o-tap",
    }
    assert hotkey._responder(estado, 0xFFFFFFFE, None) is False
    assert hotkey._responder(estado, 0xFFFFFFFF, None) is False
    assert chamadas == [("o-tap", True), ("o-tap", True)]


# ---------------------------------------------------------------- fala


def test_falando_olha_o_processo_do_audio(monkeypatch):
    monkeypatch.setattr(voz, "_FALADOR", None)
    assert voz.falando() is False

    falador = SimpleNamespace(player=SimpleNamespace(_proc=None))
    monkeypatch.setattr(voz, "_FALADOR", falador)
    assert voz.falando() is False

    falador.player._proc = object()
    assert voz.falando() is True


def test_pedir_nao_para_a_fala_sozinho(monkeypatch):
    chamadas = []
    monkeypatch.setattr(voz, "parar", lambda: chamadas.append("parar"))
    cancelar.armar(1)
    cancelar.pedir()
    assert chamadas == []
    assert cancelar.pedido() is True


def test_operario_para_a_fala(monkeypatch):
    pronto = threading.Event()

    def parar():
        pronto.set()

    monkeypatch.setattr(voz, "parar", parar)
    cancelar.iniciar()
    # nothing armed: a wake word outside a dictation still stops the speech
    cancelar.pedir()
    assert pronto.wait(timeout=2)


# ---------------------------------------------------------------- arquivo de pedido


def test_pedido_novo_cancela(monkeypatch):
    cancelar.armar(3)
    cancelar.REQUEST.parent.mkdir(parents=True, exist_ok=True)
    cancelar.REQUEST.write_text("x", encoding="utf-8")

    assert cancelar.verificar_pedido() is True
    assert cancelar.pedido() is True
    assert not cancelar.REQUEST.exists()


def test_pedido_velho_e_ignorado_e_apagado():
    cancelar.armar(3)
    cancelar.REQUEST.parent.mkdir(parents=True, exist_ok=True)
    cancelar.REQUEST.write_text("x", encoding="utf-8")
    velho = time.time() - 60
    os.utime(cancelar.REQUEST, (velho, velho))

    assert cancelar.verificar_pedido() is False
    assert cancelar.pedido() is False
    assert not cancelar.REQUEST.exists()


def test_pedido_com_relogio_injetado():
    cancelar.armar(3)
    cancelar.REQUEST.parent.mkdir(parents=True, exist_ok=True)
    cancelar.REQUEST.write_text("x", encoding="utf-8")

    # 60 s later the same file is a leftover, not a cancel
    assert cancelar.verificar_pedido(agora=time.time() + 60) is False
    assert cancelar.pedido() is False


def test_sem_arquivo_de_pedido():
    assert cancelar.verificar_pedido() is False
    assert cancelar.pedido() is False


# ---------------------------------------------------------------- ctl cancel


def test_ctl_cancel_com_lock_livre_nao_escreve(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ctl, "LOCK", tmp_path / "ronaldo.lock")
    monkeypatch.setattr(ctl, "REQUEST", tmp_path / "ronaldo" / "cancel.request")

    assert ctl.main(["cancel"]) == 1
    assert "não está ouvindo" in capsys.readouterr().err
    assert not (tmp_path / "ronaldo" / "cancel.request").exists()


def test_ctl_cancel_com_lock_preso_escreve(monkeypatch, tmp_path, capsys):
    lock_path = tmp_path / "ronaldo.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    preso = open(lock_path, "w")
    fcntl.flock(preso, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(ctl, "LOCK", lock_path)
    pedido = tmp_path / "ronaldo" / "cancel.request"
    monkeypatch.setattr(ctl, "REQUEST", pedido)
    try:
        assert ctl.main(["cancel"]) == 0
    finally:
        preso.close()

    assert capsys.readouterr().out == "Cancelado.\n"
    assert pedido.exists()
    assert pedido.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------- frame do HUD


def test_atualizar_frame_e_dentro():
    cancelar.armar(2)
    hud._FRAME.parent.mkdir(parents=True, exist_ok=True)
    hud._FRAME.write_text(json.dumps({"id": 2, "x": 10, "y": 20, "w": 100, "h": 40}), encoding="utf-8")

    cancelar.atualizar_frame()
    assert cancelar.frame() == (10.0, 20.0, 100.0, 40.0)
    assert cancelar.dentro(10, 20) is True
    assert cancelar.dentro(110, 60) is True
    assert cancelar.dentro(111, 60) is False
    assert cancelar.dentro(0, 0) is False


def test_atualizar_frame_ignora_id_errado_e_campos_invalidos():
    cancelar.armar(2)
    hud._FRAME.parent.mkdir(parents=True, exist_ok=True)

    hud._FRAME.write_text(json.dumps({"id": 9, "x": 1, "y": 2, "w": 3, "h": 4}), encoding="utf-8")
    cancelar.atualizar_frame()
    assert cancelar.frame() is None

    hud._FRAME.write_text(json.dumps({"id": 2, "x": "a", "y": 2, "w": 3, "h": 4}), encoding="utf-8")
    cancelar.atualizar_frame()
    assert cancelar.frame() is None


def test_dentro_sem_frame():
    assert cancelar.dentro(1, 2) is False


# ---------------------------------------------------------------- armar/desarmar/fechar


def test_armar_e_desarmar_limpam_o_frame():
    hud._FRAME.parent.mkdir(parents=True, exist_ok=True)
    hud._FRAME.write_text("{}", encoding="utf-8")

    cancelar.armar(1)
    assert not hud._FRAME.exists()

    hud._FRAME.write_text("{}", encoding="utf-8")
    cancelar.desarmar()
    assert not hud._FRAME.exists()


def test_armar_limpa_o_estado_anterior():
    cancelar.armar(1)
    cancelar.pedir()
    cancelar.armar(2)
    assert cancelar.pedido() is False
    assert cancelar.armado() is True


def test_desarmar_idempotente():
    cancelar.armar(1)
    cancelar.desarmar()
    cancelar.desarmar()
    assert cancelar.armado() is False
    assert cancelar.pedido() is False


def test_fechar_devolve_false_quando_pedido():
    cancelar.armar(1)
    cancelar.pedir()
    assert cancelar.fechar() is False
    assert cancelar.pedido() is True  # the state stays for the caller to see


def test_fechar_devolve_true_e_fecha_a_janela():
    cancelar.armar(1)
    assert cancelar.fechar() is True
    assert cancelar.armado() is False


def test_pedido_depois_de_fechar_nao_seta_o_evento():
    cancelar.armar(1)
    assert cancelar.fechar() is True

    cancelar.pedir()
    assert cancelar.pedido() is False
    assert cancelar.fechar() is True


# ---------------------------------------------------------------- hexcli


def test_discard_dictation_usa_cancel_quando_existe(monkeypatch):
    chamadas = []

    def run(*args, timeout=15):
        chamadas.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hexcli, "_run", run)
    hexcli.discard_dictation()
    assert chamadas == [("dictation", "cancel")]


def test_discard_dictation_cai_no_stop_print(monkeypatch):
    chamadas = []

    def run(*args, timeout=15):
        chamadas.append(args)
        return SimpleNamespace(
            returncode=2 if args == ("dictation", "cancel") else 0, stdout="texto", stderr=""
        )

    monkeypatch.setattr(hexcli, "_run", run)
    hexcli.discard_dictation()
    assert chamadas == [("dictation", "cancel"), ("dictation", "stop", "--print")]


# ---------------------------------------------------------------- gravação


def test_record_until_silence_devolve_cancelled():
    lst = _listener()
    consumidos = []

    def fonte():
        for _ in range(5):
            consumidos.append(1)
            yield np.zeros(1600, dtype=np.int16)

    assert lst._record_until_silence(fonte(), cancelled=lambda: True) == "cancelled"
    assert len(consumidos) == 1


def test_cancelar_durante_a_gravacao(monkeypatch):
    lst = _listener()
    eventos = []
    _preparar_hex(monkeypatch, eventos)
    mostrados = _huds(monkeypatch)
    monkeypatch.setattr(listener.voz, "marcar_gravando", lambda valor: eventos.append(("gravando", valor)))
    lst._record_until_silence = lambda **_kw: "cancelled"

    lst._dictate(Route(model="x", action="command", command=["/mock/agente"]))

    assert "discard" in eventos
    assert "stop" not in eventos
    assert "dispatch" not in eventos and "type" not in eventos
    assert mostrados[0][0][0] == "🎙️ Ouvindo…"
    assert mostrados[0][1]["cancel"] is True
    assert mostrados[-1][0][0] == "🚫 Cancelado"
    assert eventos[-1] == ("gravando", False)


def test_cancelar_durante_a_transcricao(monkeypatch):
    lst = _listener()
    eventos = []
    _preparar_hex(monkeypatch, eventos)
    mostrados = _huds(monkeypatch)

    def parar_e_transcrever():
        eventos.append("stop")
        cancelar.pedir()
        return "texto"

    monkeypatch.setattr(listener.hexcli, "stop_and_transcribe", parar_e_transcrever)
    lst._record_until_silence = lambda **_kw: "silence"

    lst._dictate(Route(model="x", action="command", command=["/mock/agente"]))

    assert "dispatch" not in eventos and "type" not in eventos
    assert mostrados[-1][0][0] == "🚫 Cancelado"


def test_cancelar_imediatamente_antes_do_dispatch(monkeypatch):
    lst = _listener()
    eventos = []
    _preparar_hex(monkeypatch, eventos)
    mostrados = _huds(monkeypatch)
    lst._record_until_silence = lambda **_kw: "silence"

    real_fechar = cancelar.fechar

    def fechar_com_pedido():
        cancelar.pedir()
        return real_fechar()

    monkeypatch.setattr(cancelar, "fechar", fechar_com_pedido)

    lst._dictate(Route(model="x", action="command", command=["/mock/agente"]))

    assert "dispatch" not in eventos and "type" not in eventos
    assert mostrados[-1][0][0] == "🚫 Cancelado"


def test_cancelar_depois_do_start_dictation(monkeypatch):
    lst = _listener()
    eventos = []
    _preparar_hex(monkeypatch, eventos)
    _huds(monkeypatch)
    monkeypatch.setattr(
        listener.hexcli,
        "start_dictation",
        lambda: (eventos.append("start"), cancelar.pedir(), True)[2],
    )
    lst._record_until_silence = lambda **_kw: pytest.fail("must not record after a cancel")

    lst._dictate(Route(model="x", action="command", command=["/mock/agente"]))

    assert "discard" in eventos and "stop" not in eventos
    assert "dispatch" not in eventos and "type" not in eventos


def test_cancelar_durante_o_inicio_do_hex(monkeypatch):
    lst = _listener()
    eventos = []
    _preparar_hex(monkeypatch, eventos)
    mostrados = _huds(monkeypatch)
    monkeypatch.setattr(
        listener.hexcli,
        "ensure_running",
        lambda: (cancelar.pedir(), False)[1],
    )
    lst._record_until_silence = lambda **_kw: pytest.fail("must not record after a cancel")

    lst._dictate(Route(model="x", action="command", command=["/mock/agente"]))

    assert "start" not in eventos and "discard" not in eventos
    assert mostrados[-1][0][0] == "🚫 Cancelado"


def test_cancelar_durante_a_gravacao_numa_rota_de_digitacao(monkeypatch):
    lst = _listener()
    eventos = []
    _preparar_hex(monkeypatch, eventos)
    _huds(monkeypatch)
    lst._record_until_silence = lambda **_kw: "cancelled"

    lst._dictate(Route(model="x", action="type"))

    assert "discard" in eventos
    assert "type" not in eventos


# ---------------------------------------------------------------- config


def test_config_cancel_hotkey_padrao_e_arquivo(tmp_path):
    assert Config(routes=[]).cancel_hotkey == "cmd+d"

    arquivo = tmp_path / "c.toml"
    arquivo.write_text('cancel_hotkey = "cmd+."\n')
    assert Config.load(arquivo).cancel_hotkey == "cmd+."


# ---------------------------------------------------------------- HUD


@pytest.fixture
def hud_estado():
    hud._daemon = None
    hud._seq = 0
    hud._n = 0
    yield
    hud._daemon = None
    hud._seq = 0
    hud._n = 0


def test_show_com_cancel_inclui_a_chave(monkeypatch, hud_estado):
    monkeypatch.setattr(hud.subprocess, "Popen", lambda *a, **k: _Proc())
    req_id = hud.begin()

    hud.show("t", "b", "rec", 3, req_id, cancel=True)
    assert json.loads(hud._STATE.read_text(encoding="utf-8"))["cancel"] is True

    hud.show("t", "b", "rec", 3, req_id, cancel=False)
    assert "cancel" not in json.loads(hud._STATE.read_text(encoding="utf-8"))


def test_start_apaga_frame(monkeypatch, hud_estado):
    hud._FRAME.parent.mkdir(parents=True, exist_ok=True)
    hud._FRAME.write_text("{}", encoding="utf-8")
    invocados = []

    def spawn(*args, **kwargs):
        invocados.append(args[0])
        return _Proc()

    monkeypatch.setattr(hud.subprocess, "Popen", spawn)
    hud.start()

    assert not hud._FRAME.exists()
    assert invocados[0][4:] == [str(hud._STATE), str(hud._FRAME)]


def test_read_frame_tolerante(hud_estado):
    assert hud.read_frame() is None

    hud._FRAME.parent.mkdir(parents=True, exist_ok=True)
    hud._FRAME.write_text("[1, 2]", encoding="utf-8")
    assert hud.read_frame() is None

    hud._FRAME.write_text(json.dumps({"id": 1, "x": 10, "y": 20, "w": 30, "h": 40}), encoding="utf-8")
    assert hud.read_frame() == {"id": 1, "x": 10, "y": 20, "w": 30, "h": 40}

    hud.clear_frame()
    assert not hud._FRAME.exists()
