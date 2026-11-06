import json
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ronaldo import agent, hud, listener


class Proc:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.running = True
        self.killed = False

    def poll(self):
        return None if self.running else 0

    def wait(self, timeout=None):
        if self.running:
            raise subprocess.TimeoutExpired("osascript", timeout)
        return 0

    def terminate(self):
        self.running = False

    def kill(self):
        self.killed = True
        self.running = False


def reset(monkeypatch, tmp_path):
    monkeypatch.setattr(hud, "_STATE", tmp_path / "hud.json")
    monkeypatch.setattr(hud, "_daemon", None)
    monkeypatch.setattr(hud, "_seq", 0)
    monkeypatch.setattr(hud, "_n", 0)


def test_atomic_json_and_stale_id(monkeypatch, tmp_path):
    reset(monkeypatch, tmp_path)
    proc = Proc()
    monkeypatch.setattr(hud.subprocess, "Popen", lambda *args, **kwargs: proc)

    old_id = hud.begin()
    current_id = hud.begin()
    hud.show("old", "body", req_id=old_id)
    assert not (tmp_path / "hud.json").exists()

    hud.show("title", "body", "ok", 3, current_id)
    payload = json.loads((tmp_path / "hud.json").read_text())
    assert payload == {
        "id": current_id,
        "n": 1,
        "title": "title",
        "body": "body",
        "kind": "ok",
        "seconds": 3,
    }
    assert not list(tmp_path.glob("*.tmp"))


def test_same_req_id_produces_distinct_payloads(monkeypatch, tmp_path):
    reset(monkeypatch, tmp_path)
    proc = Proc()
    monkeypatch.setattr(hud.subprocess, "Popen", lambda *args, **kwargs: proc)
    req_id = hud.begin()

    hud.show("heard", "body", req_id=req_id)
    heard = json.loads((tmp_path / "hud.json").read_text())
    hud.show("delivered", "body", req_id=req_id)
    delivered = json.loads((tmp_path / "hud.json").read_text())

    assert heard["id"] == delivered["id"] == req_id
    assert heard["n"] == 1
    assert delivered["n"] == 2
    assert delivered["title"] == "delivered"


def test_start_removes_old_state_before_spawning(monkeypatch, tmp_path):
    reset(monkeypatch, tmp_path)
    state_file = tmp_path / "hud.json"
    state_file.write_text('{"id": 99, "title": "stale"}')
    proc = Proc()

    def spawn(*args, **kwargs):
        assert not state_file.exists()
        return proc

    monkeypatch.setattr(hud.subprocess, "Popen", spawn)
    hud.start()
    assert hud._daemon is proc


def test_daemon_restarted_if_dead(monkeypatch, tmp_path):
    reset(monkeypatch, tmp_path)
    processes = []

    def spawn(*args, **kwargs):
        processes.append(Proc())
        return processes[-1]

    monkeypatch.setattr(hud.subprocess, "Popen", spawn)
    hud.start()
    processes[0].running = False
    hud.start()
    assert len(processes) == 2
    assert processes[0].poll() == 0


def test_stop_kills_stubborn_daemon(monkeypatch, tmp_path):
    reset(monkeypatch, tmp_path)
    proc = Proc()
    proc.terminate = lambda: None
    monkeypatch.setattr(hud.subprocess, "Popen", lambda *args, **kwargs: proc)

    hud.start()
    hud.stop()

    assert proc.killed
    assert hud._daemon is None


def test_show_swallows_spawn_and_write_errors(monkeypatch, tmp_path):
    reset(monkeypatch, tmp_path)
    monkeypatch.setattr(
        hud.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("spawn")),
    )
    hud.show("x", "y")

    reset(monkeypatch, tmp_path)
    monkeypatch.setattr(hud.subprocess, "Popen", lambda *args, **kwargs: Proc())
    monkeypatch.setattr(
        hud, "_write_state", lambda *_: (_ for _ in ()).throw(OSError("write"))
    )
    hud.show("x", "y")


def test_two_concurrent_threads_ignore_old_request(monkeypatch, tmp_path):
    reset(monkeypatch, tmp_path)
    proc = Proc()
    monkeypatch.setattr(hud.subprocess, "Popen", lambda *args, **kwargs: proc)
    old_id = hud.begin()
    newest_id = hud.begin()
    new_written = threading.Event()

    def show_new():
        hud.show("new", "body", req_id=newest_id)
        new_written.set()

    def show_old():
        assert new_written.wait(timeout=2)
        hud.show("old", "body", req_id=old_id)

    newer = threading.Thread(target=show_new)
    older = threading.Thread(target=show_old)
    older.start()
    newer.start()
    newer.join(timeout=2)
    older.join(timeout=2)

    payload = json.loads((tmp_path / "hud.json").read_text())
    assert not older.is_alive() and not newer.is_alive()
    assert payload["id"] == newest_id
    assert payload["title"] == "new"
    assert payload["n"] == 1


def test_blocked_notification_does_not_delay_final_hud_or_run(monkeypatch):
    import time

    calls = []
    notify_started = threading.Event()
    release_notify = threading.Event()
    monkeypatch.setattr(
        agent.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )

    def blocked_notify(*args, **kwargs):
        notify_started.set()
        release_notify.wait()

    monkeypatch.setattr(agent, "notify", blocked_notify)
    monkeypatch.setattr(hud, "show", lambda *args, **kwargs: calls.append(args))

    started = time.monotonic()
    try:
        result = agent.run(
            ["cmd"],
            "spoken words",
            path="/bin",
            timeout=1,
            notify_reply=True,
            name="route",
            hud=True,
            req_id=3,
        )
        elapsed = time.monotonic() - started
        assert result[0]
        assert elapsed < 1
        assert calls and calls[0][0].startswith("✅ ")
        assert notify_started.wait(timeout=1)
    finally:
        release_notify.set()


def test_success_hud_body_is_summarized(monkeypatch):
    calls = []
    monkeypatch.setattr(
        agent.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    monkeypatch.setattr(agent, "notify", lambda *args, **kwargs: None)
    monkeypatch.setattr(hud, "show", lambda *args, **kwargs: calls.append(args))
    long_text = "spoken words " * 100

    assert agent.run(
        ["cmd"],
        long_text,
        path="/bin",
        timeout=1,
        notify_reply=True,
        name="route",
        hud=True,
    )[0]
    assert calls[0][1] == agent.summarize(long_text)
    assert len(calls[0][1]) <= 240


def make_listener():
    instance = object.__new__(listener.Listener)
    instance.cfg = SimpleNamespace(resolved_language=lambda: "en")
    return instance


def test_listener_hex_failures_empty_and_exception_warn(monkeypatch):
    instance = make_listener()
    route = listener.Route(model="x", action="command", command=["cmd"])
    calls = []
    monkeypatch.setattr(listener.agent_hud, "begin", lambda: 1)
    monkeypatch.setattr(
        listener.agent_hud, "show", lambda *args, **kwargs: calls.append(args)
    )

    monkeypatch.setattr(listener.hexcli, "ensure_running", lambda: False)
    instance._dictate(route)
    assert calls[-1][0] == "⚠️ Não entendi"

    calls.clear()
    monkeypatch.setattr(listener.hexcli, "ensure_running", lambda: True)
    monkeypatch.setattr(listener.hexcli, "ensure_language", lambda *_: None)
    monkeypatch.setattr(listener.hexcli, "start_dictation", lambda: False)
    instance._dictate(route)
    assert calls[-1][0] == "⚠️ Não entendi"

    calls.clear()
    monkeypatch.setattr(listener.hexcli, "start_dictation", lambda: True)
    instance._record_until_silence = lambda: "silence"
    monkeypatch.setattr(listener.hexcli, "stop_and_transcribe", lambda: None)
    instance._dictate(route)
    assert calls[-1][0] == "⚠️ Não entendi"

    calls.clear()
    monkeypatch.setattr(
        listener.hexcli,
        "start_dictation",
        lambda: (_ for _ in ()).throw(RuntimeError("dictation failed")),
    )
    with pytest.raises(RuntimeError):
        instance._dictate(route)
    assert calls[-1][0] == "⚠️ Não entendi"


def test_disabled_hud_and_type_route_never_show(monkeypatch):
    instance = make_listener()
    calls = []
    monkeypatch.setattr(
        listener.agent_hud, "show", lambda *args, **kwargs: calls.append(args)
    )
    monkeypatch.setattr(listener.hexcli, "ensure_running", lambda: False)

    command_route = listener.Route(
        model="x", action="command", command=["cmd"], hud=False
    )
    type_route = listener.Route(model="x", action="type")
    instance._dictate(command_route)
    instance._dictate(type_route)
    assert not calls
