"""Routes: wake word -> type into the focused app, or dispatch to an agent command."""

import pytest

from ronaldo import agent, hexcli, macos
from ronaldo.listener import Config, Listener, Route


def write(tmp_path, body):
    p = tmp_path / "c.toml"
    p.write_text(body)
    return Config.load(p)


def test_default_is_a_single_typing_route(tmp_path):
    cfg = write(tmp_path, "silence_seconds = 3\n")
    assert [(r.action, r.model) for r in cfg.routes] == [("type", "ronaldo_ptbr.onnx")]


def test_routes_from_config(tmp_path):
    cfg = write(tmp_path, '''
[[routes]]
model = "extra/wall-e.onnx"
action = "type"

[[routes]]
model = "extra/ok_boss.onnx"
action = "command"
command = ["claude", "-p", "{text}"]
threshold = 0.6
''')
    typing, agent_route = cfg.routes
    assert typing.name == "wall-e" and typing.threshold == 0.5 and typing.press_enter
    assert agent_route.name == "ok_boss" and agent_route.command == ["claude", "-p", "{text}"]
    assert agent_route.threshold == 0.6 and agent_route.notify


def test_invalid_routes_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="command"):
        write(tmp_path, '[[routes]]\nmodel = "x.onnx"\naction = "command"\n')
    with pytest.raises(ValueError, match="action"):
        write(tmp_path, '[[routes]]\nmodel = "x.onnx"\naction = "teleport"\n')


def test_pick_route_takes_the_strongest_above_its_threshold():
    a = Route(model="a.onnx", threshold=0.5)
    b = Route(model="b.onnx", action="command", command=["x"], threshold=0.8)
    lst = Listener.__new__(Listener)
    lst.routes = {"a": a, "b": b}
    assert lst._pick({"a": 0.2, "b": 0.7}) is None  # b is below its own threshold
    assert lst._pick({"a": 0.6, "b": 0.9}) is b
    assert lst._pick({"a": 0.6, "b": 0.1}) is a


def _listener_with(monkeypatch, route, text):
    monkeypatch.setattr(hexcli, "ensure_running", lambda: True)
    monkeypatch.setattr(hexcli, "ensure_language", lambda lang: True)
    monkeypatch.setattr(hexcli, "start_dictation", lambda: True)
    monkeypatch.setattr(hexcli, "stop_and_transcribe", lambda: text)
    lst = Listener.__new__(Listener)
    lst.cfg = Config(routes=[route])
    lst.path = "/usr/bin:/bin"
    monkeypatch.setattr(lst, "_record_until_silence", lambda: "silence")
    return lst


def test_typing_route_pastes(monkeypatch):
    typed = []
    monkeypatch.setattr(macos, "type_and_submit", lambda text, submit: typed.append((text, submit)))
    lst = _listener_with(monkeypatch, Route(model="w.onnx"), "olá mundo")
    lst._dictate(lst.cfg.routes[0])
    assert typed == [("olá mundo", True)]


def test_command_route_dispatches_instead_of_typing(monkeypatch):
    typed, sent = [], []
    monkeypatch.setattr(macos, "type_and_submit", lambda *a, **k: typed.append(a))
    monkeypatch.setattr(agent, "dispatch", lambda template, text, **kw: sent.append((template, text, kw["name"])))
    route = Route(model="boss.onnx", action="command", command=["agente", "{text}"])
    lst = _listener_with(monkeypatch, route, "abre o PR")
    lst._dictate(route)
    assert typed == [] and sent == [(["agente", "{text}"], "abre o PR", "boss")]


def test_agent_gets_text_as_argv_or_stdin():
    assert agent.build_argv(["claude", "-p", "{text}"], 'diz "oi"; rm -rf ~') == (["claude", "-p", 'diz "oi"; rm -rf ~'], None)
    assert agent.build_argv(["hermes", "chat"], "faz X") == (["hermes", "chat"], "faz X")


def test_agent_reply_becomes_a_notification(monkeypatch):
    pushed = []
    monkeypatch.setattr(agent, "notify", lambda msg, title: pushed.append((title, msg)))
    ok, _ = agent.run(["/bin/echo", "Beleza, botei o Codex pra fazer: {text}"], "abrir o PR", path="/bin", timeout=10, notify_reply=True, name="boss")
    assert ok and pushed == [("Ronaldo · boss", "Beleza, botei o Codex pra fazer: abrir o PR")]


def test_stdin_route_receives_the_text(monkeypatch):
    pushed = []
    monkeypatch.setattr(agent, "notify", lambda msg, title: pushed.append(msg))
    agent.run(["/bin/cat"], "via stdin", path="/bin", timeout=10, notify_reply=True, name="x")
    assert pushed == ["via stdin"]


def test_failures_are_reported_not_swallowed(monkeypatch):
    pushed = []
    monkeypatch.setattr(agent, "notify", lambda msg, title: pushed.append(msg))
    assert agent.run(["/usr/bin/false"], "x", path="/usr/bin", timeout=10, notify_reply=True, name="x")[0] is False
    assert agent.run(["nao-existe-123"], "x", path="/usr/bin", timeout=10, notify_reply=True, name="x")[0] is False
    assert agent.run(["/bin/sleep", "5"], "x", path="/bin", timeout=0.5, notify_reply=True, name="x")[0] is False
    assert pushed[0].startswith("O agente falhou (código 1)")
    assert pushed[1] == "Comando não encontrado: nao-existe-123"
    assert pushed[2].startswith("O agente não respondeu")


def test_long_replies_are_trimmed_for_the_push():
    assert len(agent.summarize("palavra " * 200)) == agent.NOTIFY_CHARS
