from __future__ import annotations

import subprocess
import threading
from types import SimpleNamespace

from ronaldo import agent, hud, listener


class Proc:
    def __init__(self, args, **kw):
        self.args = args
        self.alive = True
        self.killed = False
    def wait(self, timeout=None):
        if self.alive:
            if timeout is not None:
                raise subprocess.TimeoutExpired("osascript", timeout)
        return 0
    def terminate(self): self.alive = False
    def kill(self): self.killed = True; self.alive = False


def reset(monkeypatch):
    monkeypatch.setattr(hud, "_current", None)
    monkeypatch.setattr(hud, "_seq", 0)
    monkeypatch.setattr(hud.subprocess, "Popen", Proc)


def test_begin_and_stale_request(monkeypatch):
    reset(monkeypatch)
    one, two = hud.begin(), hud.begin()
    hud.show("old", "body", req_id=one)
    assert hud._current is None
    hud.show("new", "body", req_id=two)
    assert hud._current.args[4] == "new"


def test_replacement_terminates_old(monkeypatch):
    reset(monkeypatch)
    hud.show("one", "a")
    first = hud._current
    hud.show("two", "b")
    assert first.alive is False
    assert hud._current.args[4] == "two"


def test_hud_spawn_failure_is_swallowed(monkeypatch):
    reset(monkeypatch)
    def fail(*a, **k): raise OSError("no osascript")
    monkeypatch.setattr(hud.subprocess, "Popen", fail)
    hud.show("x", "y")


def test_stuck_process_killed_and_reaped(monkeypatch):
    reset(monkeypatch)
    p = Proc([],)
    p.wait = lambda timeout=None: (_ for _ in ()).throw(subprocess.TimeoutExpired("osascript", timeout))
    p.kill = lambda: setattr(p, "killed", True)
    monkeypatch.setattr(hud.subprocess, "Popen", lambda *a, **k: p)
    hud._reap(p, 0)
    assert p.killed


def test_run_ok_error_and_notify_failure(monkeypatch):
    calls=[]
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="Entregue ao rei do Pessoal.", stderr=""))
    monkeypatch.setattr(agent, "notify", lambda *a, **k: (_ for _ in ()).throw(OSError("notify")))
    monkeypatch.setattr(hud, "show", lambda *a, **k: calls.append((a,k)))
    assert agent.run(["corte","falar","{text}"], "fala", path="/bin", timeout=1, notify_reply=True, name="pessoal", hud=True, req_id=8)[0]
    assert calls[-1][0][0] == "✅ Entregue ao rei do Pessoal."
    assert calls[-1][0][1] == "fala"
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="erro"))
    assert not agent.run(["x"], "fala", path="/bin", timeout=1, notify_reply=False, name="pessoal", hud=True)[0]
    assert calls[-1][0][0] == "❌ Não entregou"


def test_run_not_found_and_timeout(monkeypatch):
    calls=[]
    monkeypatch.setattr(hud, "show", lambda *a, **k: calls.append(a))
    def missing(*a, **k): raise FileNotFoundError()
    monkeypatch.setattr(agent.subprocess, "run", missing)
    assert not agent.run(["missing"], "x", path="/bin", timeout=1, notify_reply=False, name="r", hud=True)[0]
    def timeout(*a, **k): raise subprocess.TimeoutExpired("x", 1)
    monkeypatch.setattr(agent.subprocess, "run", timeout)
    assert not agent.run(["x"], "x", path="/bin", timeout=1, notify_reply=False, name="r", hud=True)[0]
    assert len(calls) == 2


def test_dictation_failure_empty_and_disabled(monkeypatch):
    route=listener.Route(model="x", action="command", command=["x"])
    l=object.__new__(listener.Listener); l.cfg=SimpleNamespace(resolved_language=lambda:"en")
    calls=[]; monkeypatch.setattr(listener.agent_hud,"begin",lambda:1); monkeypatch.setattr(listener.agent_hud,"show",lambda *a,**k:calls.append(a))
    monkeypatch.setattr(listener.hexcli,"ensure_running",lambda:False)
    l._dictate(route); assert calls[-1][0] == "⚠️ Não entendi"
    calls.clear(); monkeypatch.setattr(listener.hexcli,"ensure_running",lambda:True); monkeypatch.setattr(listener.hexcli,"ensure_language",lambda x:None); monkeypatch.setattr(listener.hexcli,"start_dictation",lambda:False)
    l._dictate(route); assert calls[-1][0] == "⚠️ Não entendi"
    calls.clear(); route.hud=False; l._dictate(route); assert not calls


def test_empty_and_exception_report_warn(monkeypatch):
    route=listener.Route(model="x", action="command", command=["x"])
    l=object.__new__(listener.Listener); l.cfg=SimpleNamespace(resolved_language=lambda:"en")
    calls=[]; monkeypatch.setattr(listener.agent_hud,"begin",lambda:2); monkeypatch.setattr(listener.agent_hud,"show",lambda *a,**k:calls.append(a))
    monkeypatch.setattr(listener.hexcli,"ensure_running",lambda:True); monkeypatch.setattr(listener.hexcli,"ensure_language",lambda x:None); monkeypatch.setattr(listener.hexcli,"start_dictation",lambda:True)
    l._record_until_silence=lambda:"silence"; monkeypatch.setattr(listener.hexcli,"stop_and_transcribe",lambda:None)
    l._dictate(route); assert calls[-1][0] == "⚠️ Não entendi"
    monkeypatch.setattr(listener.hexcli,"start_dictation",lambda:(_ for _ in ()).throw(RuntimeError("ditado falhou")))
    try: l._dictate(route)
    except RuntimeError: pass
    assert calls[-1][0] == "⚠️ Não entendi"


def test_type_route_does_not_show_hud(monkeypatch):
    route=listener.Route(model="x", action="type")
    l=object.__new__(listener.Listener); l.cfg=SimpleNamespace(resolved_language=lambda:"en")
    calls=[]; monkeypatch.setattr(listener.agent_hud,"show",lambda *a,**k:calls.append(a))
    monkeypatch.setattr(listener.hexcli,"ensure_running",lambda:False)
    l._dictate(route); assert not calls


def test_two_threads_keep_latest_and_reap_children(monkeypatch):
    reset(monkeypatch)
    start=threading.Barrier(2)
    spawned=[]
    def factory(*args, **kw):
        proc=Proc(*args, **kw); spawned.append(proc); return proc
    monkeypatch.setattr(hud.subprocess, "Popen", factory)
    ids={}
    def run(title):
        ids[title]=hud.begin(); start.wait(); hud.show(title,title,req_id=ids[title])
    a=threading.Thread(target=run,args=("a",)); b=threading.Thread(target=run,args=("b",))
    a.start(); b.start(); a.join(); b.join()
    latest=max(ids, key=ids.get)
    assert len(spawned) == 1
    assert spawned[0].args[4] == latest
    assert all(not p.alive for p in spawned)


def test_notify_timeout_does_not_hide_final_hud(monkeypatch):
    calls=[]
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok", stderr=""))
    monkeypatch.setattr(agent, "notify", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("osascript", 10)))
    monkeypatch.setattr(hud, "show", lambda *a, **k: calls.append(a))
    assert agent.run(["cmd"], "fala", path="/bin", timeout=1, notify_reply=True, name="r", hud=True)[0]
    assert calls and calls[0][0].startswith("✅ ")


def test_success_hud_body_is_summarized(monkeypatch):
    calls=[]
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok", stderr=""))
    monkeypatch.setattr(agent, "notify", lambda *a, **k: None)
    monkeypatch.setattr(hud, "show", lambda *a, **k: calls.append(a))
    long_text = "fala " * 100
    assert agent.run(["cmd"], long_text, path="/bin", timeout=1, notify_reply=True, name="r", hud=True)[0]
    assert calls[0][1] == agent.summarize(long_text)
    assert len(calls[0][1]) <= 240
