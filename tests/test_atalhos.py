import json
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ronaldo import agent
from ronaldo.atalhos import casar, entregar_terminal


def result(data=None, rc=0, stderr=""):
    return SimpleNamespace(returncode=rc, stdout=json.dumps(data) if not isinstance(data, str) else data, stderr=stderr)


def setup_calls(monkeypatch, responses):
    calls = []
    def fake(argv, **kwargs):
        calls.append(argv)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    monkeypatch.setattr("ronaldo.atalhos.shutil.which", lambda *a, **k: "/mock/hc")
    monkeypatch.setattr("ronaldo.atalhos.subprocess.run", fake)
    return calls


def live(state="done", turn=4, **overrides):
    info = {"address": "ADDR", "created_ms": 123, "state": "live", "turn": turn,
            "status": {"app": "claude-code", "state": state},
            "labels": {"reino.batuqueiro": "1"}}
    info.update(overrides)
    return info


def test_guards_and_blocked_never_send(monkeypatch):
    dead = live()
    dead["state"] = "dead"
    bads = [dead, live(status={"app": "shell", "state": "done"}), live(labels={})]
    for info in bads:
        calls = setup_calls(monkeypatch, [result(info)])
        assert entregar_terminal("term", "pedido", path="/mock") [0] == "falhou"
        assert len(calls) == 1 and "keys" not in calls[0] and "send" not in calls[0]
    calls = setup_calls(monkeypatch, [result(live(state="blocked"))])
    assert entregar_terminal("term", "pedido", path="/mock")[0] == "falhou"
    assert len(calls) == 1


def test_working_sends_without_ctrl_u_and_turn_confirms(monkeypatch):
    calls = setup_calls(monkeypatch, [result(live("working", 4)), result({"started": True}), result(live("working", 5))])
    assert entregar_terminal("term", "pedido", path="/mock") == ("entregue", "Entregue ao term.")
    assert [c[1:3] for c in calls] == [["get", "term"], ["send", "ADDR"], ["get", "ADDR"]]


def test_done_ctrl_u_started_false_enters_once(monkeypatch):
    calls = setup_calls(monkeypatch, [result(live()), result({}), result({"started": False}), result({}), result(live("working", 5))])
    assert entregar_terminal("term", "pedido", path="/mock")[0] == "entregue"
    assert [c[1:3] for c in calls] == [["get", "term"], ["keys", "ADDR"], ["send", "ADDR"], ["keys", "ADDR"], ["get", "ADDR"]]
    assert calls[1][3] == "ctrl+u" and calls[3][3] == "enter"


def test_started_true_no_enter_and_no_confirmation_if_only_working(monkeypatch):
    calls = setup_calls(monkeypatch, [result(live()), result({}), result({"started": True}), result(live("working", 4))])
    ticks = iter([0, 0, 5])
    monkeypatch.setattr("ronaldo.atalhos.time.monotonic", lambda: next(ticks))
    assert entregar_terminal("term", "pedido", path="/mock", timeout=3)[0] == "sem_confirmacao"
    assert not any(c[1:3] == ["keys", "ADDR"] and c[3] == "enter" for c in calls)


@pytest.mark.parametrize("send_result", [result({"other": True}), result("{"), result({}, rc=1, stderr="send failed"), subprocess.TimeoutExpired("hc", 10)])
def test_send_errors_are_uncertain_and_never_retried(monkeypatch, send_result):
    calls = setup_calls(monkeypatch, [result(live()), result({}), send_result])
    status, message = entregar_terminal("term", "pedido", path="/mock")
    assert status == "falhou" and "incerta" in message
    assert sum(c[1] == "send" for c in calls) == 1


def test_missing_hc_and_empty_remainder(monkeypatch):
    monkeypatch.setattr("ronaldo.atalhos.shutil.which", lambda *a, **k: None)
    assert entregar_terminal("term", "pedido", path="/mock")[0] == "falhou"
    assert entregar_terminal("term", "  ", path="/mock")[0] == "falhou"


def test_match_preserves_remainder():
    shortcuts = [{"palavras": ["batuqueiro"], "terminal": "t", "nome": "batuqueiro"}]
    assert casar("Batuqueiro, toca São-João https://x.y/z?a=1", shortcuts)[1] == "toca São-João https://x.y/z?a=1"


def test_lock_keeps_deliveries_sequential(monkeypatch):
    entered = []
    gate = threading.Event()
    def fake(argv, **kwargs):
        if argv[1] == "get":
            if argv[2] == "t":
                return result(live("working", 0))
            return result(live("working", 1))
        if argv[1] == "send":
            entered.append(argv[3])
            if len(entered) == 1:
                gate.wait(1)
            return result({"started": True})
        raise AssertionError(argv)
    monkeypatch.setattr("ronaldo.atalhos.shutil.which", lambda *a, **k: "/mock/hc")
    monkeypatch.setattr("ronaldo.atalhos.subprocess.run", fake)
    # Each call sees the same top-level terminal state; the lock still prevents
    # the second send from occurring before the first confirmation poll.
    first = threading.Thread(target=entregar_terminal, args=("t", "one"), kwargs={"path": "/mock", "timeout": 0.001})
    second = threading.Thread(target=entregar_terminal, args=("t", "two"), kwargs={"path": "/mock", "timeout": 0.001})
    first.start()
    while not entered:
        pass
    second.start()
    gate.set()
    first.join()
    second.join()
    assert entered == ["one", "two"]


def test_agent_shortcut_hud_and_no_fallback(monkeypatch):
    shortcut = {"palavras": ["batuqueiro"], "terminal": "t", "nome": "Batuqueiro"}
    monkeypatch.setattr("ronaldo.atalhos.entregar_terminal", lambda *a, **k: ("entregue", "Entregue ao Batuqueiro."))
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: pytest.fail("corte chamado"))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    assert agent.run(["corte"], "batuqueiro, toca", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=99, atalhos=[shortcut])[0]
    assert shown[-1][2:4] == ("ok", 6) and shown[-1][-1] == 99
    monkeypatch.setattr("ronaldo.atalhos.entregar_terminal", lambda *a, **k: ("falhou", "nope"))
    assert not agent.run(["corte"], "batuqueiro, toca", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=100, atalhos=[shortcut])[0]
    assert shown[-1][2:4] == ("err", 12) and shown[-1][-1] == 100
    assert shown[-1][1] == "nope"
    monkeypatch.setattr("ronaldo.atalhos.entregar_terminal", lambda *a, **k: ("sem_confirmacao", "Enviado ao Batuqueiro, sem confirmação"))
    assert agent.run(["corte"], "batuqueiro, toca", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=101, atalhos=[shortcut])[0]
    assert shown[-1][2:4] == ("warn", 6) and shown[-1][-1] == 101
    shown.clear()
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="fallback", stderr=""))
    assert agent.run(["echo", "fallback"], "fala pro batuqueiro", path="/bin", timeout=1, notify_reply=False, name="rota", hud=False, atalhos=[shortcut])[0]
    assert not shown


def test_first_of_two_shortcuts_matches_and_matched_hud_can_be_disabled(monkeypatch):
    shortcuts = [
        {"palavras": ["primeiro"], "terminal": "t1"},
        {"palavras": ["batuqueiro"], "terminal": "t2", "nome": "Batuqueiro"},
    ]
    assert casar("Batuqueiro, toca", shortcuts)[0] is shortcuts[1]
    monkeypatch.setattr("ronaldo.atalhos.entregar_terminal", lambda *a, **k: ("entregue", "ok"))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    assert agent.run(["corte"], "batuqueiro, toca", path="/mock", timeout=1, notify_reply=False, name="rota", hud=False, atalhos=shortcuts)[0]
    assert not shown


@pytest.mark.parametrize("payload", [{**live(), "status": None}, {**live(), "labels": None}, [], None])
def test_invalid_initial_todo_fails_before_send(monkeypatch, payload):
    calls = setup_calls(monkeypatch, [result(payload)])
    status, message = entregar_terminal("term", "pedido", path="/mock")
    assert status == "falhou" and "resposta inválida de hc" in message
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [[], None, {**live(), "labels": None}])
def test_invalid_confirmation_is_uncertain(monkeypatch, payload):
    calls = setup_calls(monkeypatch, [result(live()), result({}), result({"started": True}), result(payload)])
    status, message = entregar_terminal("term", "pedido", path="/mock")
    assert status == "falhou" and "incerta" in message


@pytest.mark.parametrize("started", [None, "false", 0, "missing"])
def test_invalid_started_is_uncertain_without_enter(monkeypatch, started):
    data = {} if started == "missing" else {"started": started}
    calls = setup_calls(monkeypatch, [result(live()), result({}), result(data)])
    status, message = entregar_terminal("term", "pedido", path="/mock")
    assert status == "falhou" and "incerta" in message
    assert not any(c[1:3] == ["keys", "ADDR"] and c[3] == "enter" for c in calls)


@pytest.mark.parametrize("changed", [{"created_ms": 124}, {"status": {"app": "shell", "state": "working"}}, {"labels": {}}, {"turn": 100}])
def test_confirmation_of_replaced_todo_is_uncertain(monkeypatch, changed):
    confirmation = live("working", 5)
    confirmation.update(changed)
    calls = setup_calls(monkeypatch, [result(live()), result({}), result({"started": True}), result(confirmation)])
    status, message = entregar_terminal("term", "pedido", path="/mock")
    assert status == "falhou" and "incerta" in message and "foi substituído durante a entrega" in message


def test_hc_json_error_uses_message_only(monkeypatch):
    calls = setup_calls(monkeypatch, [result(live("working")), result({}, rc=1, stderr='{"error":{"message":"sem terminal"}}')])
    status, message = entregar_terminal("term", "pedido", path="/mock")
    assert status == "falhou" and message.endswith("sem terminal") and '{"error"' not in message


def test_agent_shortcut_unexpected_exception_shows_error_hud_and_returns(monkeypatch):
    shortcut = {"palavras": ["batuqueiro"], "terminal": "t", "nome": "Batuqueiro"}
    monkeypatch.setattr("ronaldo.atalhos.entregar_terminal", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("inesperado")))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    result_value = agent.run(["corte"], "batuqueiro, toca", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=102, atalhos=[shortcut])
    assert result_value == (False, "inesperado")
    assert shown[-1][0].startswith("❌") and shown[-1][2] == "err"


# ---------------------------------------------------------------- atalho com comando (gol do Rematch)

GOL = {"palavras": ["gol gol gol", "golaço", "gol"], "comando": ["/usr/bin/afplay", "-v", "0.6", "~/Music/Reino/gol-rematch.wav"], "nome": "gol"}


@pytest.mark.parametrize("texto", ["Ronaldo, gol!", "gol", "Golaço!", "Ronaldo, gol gol gol.", "GOL GOL GOL", "gol, que lindo"])
def test_atalho_de_comando_casa_fala_curta(texto):
    assert casar(texto, [GOL])[0] is GOL


@pytest.mark.parametrize("texto", ["gol do time adversário no último minuto de jogo", "golpe de mestre", "o gol", "Ronaldo, gol do Fulano no Rematch hoje cedo"])
def test_atalho_de_comando_nao_pega_frase_comum(texto):
    assert casar(texto, [GOL]) is None


def test_max_palavras_configuravel_e_terminal_sem_limite():
    assert casar("gol a b c d e f", [{**GOL, "max_palavras": 10}]) is not None
    bat = {"palavras": ["batuqueiro"], "terminal": "t"}
    assert casar("batuqueiro toca a música mais longa que existir agora", [bat]) is not None


def test_executar_comando_expande_til_e_nao_espera(monkeypatch, tmp_path):
    from ronaldo import atalhos
    monkeypatch.setenv("HOME", str(tmp_path))
    vistos = []
    monkeypatch.setattr(atalhos.subprocess, "Popen", lambda argv, **kw: vistos.append((argv, kw)) or SimpleNamespace(pid=1))
    status, msg = atalhos.executar_comando(GOL["comando"], path="/usr/bin:/bin", nome="gol")
    assert status == "entregue" and "gol" in msg
    argv, kw = vistos[0]
    assert argv == ["/usr/bin/afplay", "-v", "0.6", f"{tmp_path}/Music/Reino/gol-rematch.wav"]
    assert kw.get("start_new_session") is True and kw["stdin"] == subprocess.DEVNULL


def test_executar_comando_falha_vira_falhou(monkeypatch):
    from ronaldo import atalhos
    def boom(*a, **k): raise FileNotFoundError("afplay")
    monkeypatch.setattr(atalhos.subprocess, "Popen", boom)
    status, msg = atalhos.executar_comando(["/nao/existe"], path="/bin", nome="gol")
    assert status == "falhou" and "afplay" in msg


def test_agent_atalho_de_comando_nao_chama_o_rei_nem_o_modo_voz(monkeypatch):
    from ronaldo import voz
    monkeypatch.setattr(voz, "ligado", lambda *a, **k: True)
    monkeypatch.setattr(agent, "_falar_ao_rei", lambda *a, **k: pytest.fail("modo voz chamado"))
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: pytest.fail("corte chamado"))
    monkeypatch.setattr("ronaldo.atalhos.entregar_terminal", lambda *a, **k: pytest.fail("hc chamado"))
    rodou = []
    monkeypatch.setattr("ronaldo.atalhos.executar_comando", lambda argv, **k: rodou.append(argv) or ("entregue", "Tocou gol."))
    shown = []
    monkeypatch.setattr("ronaldo.hud.show", lambda *a: shown.append(a))
    ok, msg = agent.run(["corte", "falar", "{text}"], "Ronaldo, gol!", path="/mock", timeout=1, notify_reply=False, name="rota", hud=True, req_id=7, atalhos=[GOL], voz=True)
    assert ok and rodou == [GOL["comando"]]
    assert shown[-1][2] == "ok"


# ---------------------------------------------------------------- gol em qualquer posição (fala real "Do gol porra.")

GOL_QQ = {**GOL, "qualquer_posicao": True}


@pytest.mark.parametrize("texto", ["Do gol porra.", "gol porra", "do gol porra", "que golaço", "gol caralho", "Goool!",
                                   "GOOOOL porra", "Ronaldo, gol, porra!", "que golaaaaço", "gol"])
def test_gol_em_qualquer_posicao_frases_reais(texto):
    assert casar(texto, [GOL_QQ])[0] is GOL_QQ


@pytest.mark.parametrize("texto", ["o gol do time adversário no último minuto", "golpe de mestre", "goleiro defendeu",
                                   "Ronaldo, que horas são", "gola da camisa"])
def test_gol_em_qualquer_posicao_nao_pega(texto):
    assert casar(texto, [GOL_QQ]) is None


def test_sem_qualquer_posicao_continua_so_no_comeco():
    assert casar("do gol porra", [GOL]) is None
