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
    info = {"address": "ADDR", "state": "live", "turn": turn,
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
    calls = setup_calls(monkeypatch, [result(live("working", 4)), result({"started": True}), result({"turn": 5, "status": {"state": "working"}})])
    assert entregar_terminal("term", "pedido", path="/mock") == ("entregue", "Entregue ao term.")
    assert [c[1:3] for c in calls] == [["get", "term"], ["send", "ADDR"], ["get", "ADDR"]]


def test_done_ctrl_u_started_false_enters_once(monkeypatch):
    calls = setup_calls(monkeypatch, [result(live()), result({}), result({"started": False}), result({}), result({"turn": 5})])
    assert entregar_terminal("term", "pedido", path="/mock")[0] == "entregue"
    assert [c[1:3] for c in calls] == [["get", "term"], ["keys", "ADDR"], ["send", "ADDR"], ["keys", "ADDR"], ["get", "ADDR"]]
    assert calls[1][3] == "ctrl+u" and calls[3][3] == "enter"


def test_started_true_no_enter_and_no_confirmation_if_only_working(monkeypatch):
    calls = setup_calls(monkeypatch, [result(live()), result({}), result({"started": True}), result({"turn": 4, "status": {"state": "working"}})])
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
            return result({"turn": 1})
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
