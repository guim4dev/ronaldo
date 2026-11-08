"""ronaldo on|off|status against a fake launchctl and hex."""

from __future__ import annotations

import plistlib
import subprocess

import pytest

from ronaldo import ctl


class FakeMac:
    """Just enough launchctl and hex: a service that can be loaded and disabled, and Hex."""

    def __init__(
        self,
        loaded=True,
        disabled=False,
        hex_running=True,
        hex_busy=False,
        service_stuck=False,
        hex_stubborn=False,
        failures=None,
        bootstrap_loads=True,
        disable_persists=True,
    ):
        self.loaded, self.disabled, self.hex_running, self.hex_busy = loaded, disabled, hex_running, hex_busy
        self.service_stuck, self.hex_stubborn = service_stuck, hex_stubborn
        self.failures = failures or {}
        self.bootstrap_loads = bootstrap_loads
        self.disable_persists = disable_persists
        self.calls: list[tuple[str, ...]] = []

    def run(self, *argv):
        self.calls.append(argv)
        rc, out = 0, ""
        if argv[0] == "launchctl":
            verb = argv[1]
            rc = self.failures.get(verb, 0)
            if verb == "print":
                rc = 0 if self.loaded else 113
            elif verb == "print-disabled":
                out = f'\t"{ctl.label()}" => {"disabled" if self.disabled else "enabled"}\n'
            elif verb == "disable":
                if rc == 0 and self.disable_persists:
                    self.disabled = True
            elif verb == "enable":
                if rc == 0:
                    self.disabled = False
            elif verb == "bootout":
                if not self.service_stuck:
                    self.loaded = False
            elif verb == "bootstrap":
                if rc == 0 and self.bootstrap_loads:
                    self.loaded = True
        else:  # hex
            verb = argv[1]
            rc = self.failures.get(verb, 0)
            if verb == "status":
                rc = 0 if self.hex_running else 3
            elif verb == "quit":
                if self.hex_busy:
                    rc = 1
                elif not self.hex_stubborn:
                    self.hex_running = False
            elif verb == "start":
                if rc == 0:
                    self.hex_running = True
            elif verb == "launch-at-login":
                pass
        return subprocess.CompletedProcess(argv, rc, out, "")


@pytest.fixture
def mac(monkeypatch, tmp_path):
    fake = FakeMac()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("RONALDO_LABEL", raising=False)
    monkeypatch.setattr(ctl, "ESPERA", 0.05)
    plist = ctl.plist()
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text("")
    hexbin = tmp_path / "hex"
    hexbin.write_text("")
    monkeypatch.setattr(ctl, "_run", fake.run)
    monkeypatch.setattr(ctl, "HEX", str(hexbin))
    return fake


def test_status_is_the_default(mac, capsys):
    assert ctl.main([]) == 0
    assert capsys.readouterr().out == "ronaldo: ligado\nhex: ligado\n"


def test_off_stops_both_and_keeps_them_off_at_login(mac, capsys):
    assert ctl.main(["off"]) == 0
    assert not mac.loaded and mac.disabled and not mac.hex_running
    assert ("launch-at-login", "off") in [c[1:] for c in mac.calls]
    assert capsys.readouterr().out == "ronaldo: desligado (não sobe no login)\nhex: desligado\n"


def test_off_leaves_closed_hex_alone_and_warns_about_login(mac, capsys):
    mac.hex_running = False

    assert ctl.main(["off"]) == 0
    out = capsys.readouterr()
    hex_calls = [call[1:] for call in mac.calls if call[0] != "launchctl"]
    assert hex_calls and all(call == ("status", "--json") for call in hex_calls)
    assert "ronaldo off" in out.err and "login" in out.err
    assert not mac.loaded and mac.disabled


def test_off_reports_hex_busy_and_leaves_it_running(mac, capsys):
    mac.hex_busy = True
    assert ctl.main(["off"]) == 1
    out = capsys.readouterr()
    assert "Hex está ditando" in out.err
    assert not mac.loaded and mac.hex_running


def test_off_fails_when_hex_stays_running_after_a_successful_quit(mac, capsys):
    mac.hex_stubborn = True
    assert ctl.main(["off"]) == 1
    out = capsys.readouterr()
    assert "Hex não parou a tempo" in out.err
    assert not mac.loaded and mac.hex_running


def test_off_fails_when_the_service_does_not_unload(mac, capsys):
    mac.service_stuck = True
    assert ctl.main(["off"]) == 1
    out = capsys.readouterr()
    assert "Ronaldo não parou a tempo" in out.err
    assert mac.loaded and not mac.hex_running


def test_off_reports_disable_failure_but_still_stops_both(mac, capsys):
    mac.failures["disable"] = 1

    assert ctl.main(["off"]) == 1
    out = capsys.readouterr()
    assert "O Ronaldo não foi desativado" in out.err
    assert not mac.loaded and not mac.hex_running


def test_off_reports_when_disable_does_not_persist(mac, capsys):
    mac.disable_persists = False

    assert ctl.main(["off"]) == 1
    out = capsys.readouterr()
    assert "O Ronaldo não foi desativado" in out.err
    assert not mac.disabled and not mac.loaded and not mac.hex_running


def test_off_reports_hex_login_failure_but_still_quits_hex(mac, capsys):
    mac.failures["launch-at-login"] = 1

    assert ctl.main(["off"]) == 1
    out = capsys.readouterr()
    assert "O Hex continua abrindo no login" in out.err
    assert not mac.loaded and not mac.hex_running


def test_on_brings_both_back(mac, capsys):
    ctl.main(["off"])
    capsys.readouterr()
    assert ctl.main(["on"]) == 0
    assert mac.loaded and not mac.disabled and mac.hex_running
    assert capsys.readouterr().out == "ronaldo: ligado\nhex: ligado\n"


def test_on_does_not_bootstrap_a_loaded_service(mac):
    ctl.main(["on"])
    assert not [c for c in mac.calls if c[:2] == ("launchctl", "bootstrap")]


def test_on_without_install(mac, capsys):
    ctl.plist().unlink()
    assert ctl.main(["on"]) == 1
    assert "install.sh" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("failure", "expected"),
    [("start", "O Hex não abriu"), ("enable", "O Ronaldo não foi habilitado"),
     ("bootstrap", "O Ronaldo não abriu")],
)
def test_on_reports_command_failures(mac, capsys, failure, expected):
    mac.loaded = False
    mac.failures[failure] = 1

    assert ctl.main(["on"]) == 1
    out = capsys.readouterr()
    assert expected in out.err
    assert "ronaldo: desligado" in out.out


def test_on_fails_when_service_does_not_load_after_bootstrap(mac, capsys):
    mac.loaded = False
    mac.bootstrap_loads = False

    assert ctl.main(["on"]) == 1
    out = capsys.readouterr()
    assert "não ligou a tempo" in out.err
    assert "ronaldo: desligado" in out.out


def test_unknown_command(mac, capsys):
    assert ctl.main(["talvez"]) == 2
    assert capsys.readouterr().err.strip() == ctl.USO


def test_label_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("RONALDO_LABEL", "com.exemplo.ronaldo")
    assert ctl.label() == "com.exemplo.ronaldo"


def test_label_comes_from_the_app_info_plist(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("RONALDO_LABEL", raising=False)
    info = tmp_path / "Applications" / "Ronaldo.app" / "Contents" / "Info.plist"
    info.parent.mkdir(parents=True)
    with open(info, "wb") as arquivo:
        plistlib.dump({"CFBundleIdentifier": "com.exemplo.ronaldo"}, arquivo)
    assert ctl.label() == "com.exemplo.ronaldo"


def test_label_falls_back_without_env_or_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("RONALDO_LABEL", raising=False)
    assert ctl.label() == "io.github.ronaldo"


def test_label_ignores_a_broken_app_info_plist(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("RONALDO_LABEL", raising=False)
    info = tmp_path / "Applications" / "Ronaldo.app" / "Contents" / "Info.plist"
    info.parent.mkdir(parents=True)
    info.write_text("não é um plist")
    assert ctl.label() == "io.github.ronaldo"


def test_plist_path_follows_the_resolved_label(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RONALDO_LABEL", "com.exemplo.ronaldo")
    assert ctl.plist() == tmp_path / "Library" / "LaunchAgents" / "com.exemplo.ronaldo.plist"
