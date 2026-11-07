"""ronaldo on|off|status against a fake launchctl and hex."""

from __future__ import annotations

import subprocess

import pytest

from ronaldo import ctl


class FakeMac:
    """Just enough launchctl and hex: a service that can be loaded and disabled, and Hex."""

    def __init__(self, loaded=True, disabled=False, hex_running=True, hex_busy=False):
        self.loaded, self.disabled, self.hex_running, self.hex_busy = loaded, disabled, hex_running, hex_busy
        self.calls: list[tuple[str, ...]] = []

    def run(self, *argv):
        self.calls.append(argv)
        rc, out = 0, ""
        if argv[0] == "launchctl":
            verb = argv[1]
            if verb == "print":
                rc = 0 if self.loaded else 113
            elif verb == "print-disabled":
                out = f'\t"{ctl.LABEL}" => {"disabled" if self.disabled else "enabled"}\n'
            elif verb == "disable":
                self.disabled = True
            elif verb == "enable":
                self.disabled = False
            elif verb == "bootout":
                self.loaded = False
            elif verb == "bootstrap":
                self.loaded = True
        else:  # hex
            verb = argv[1]
            if verb == "status":
                rc = 0 if self.hex_running else 3
            elif verb == "quit":
                if self.hex_busy:
                    rc = 1
                else:
                    self.hex_running = False
            elif verb == "start":
                self.hex_running = True
        return subprocess.CompletedProcess(argv, rc, out, "")


@pytest.fixture
def mac(monkeypatch, tmp_path):
    fake = FakeMac()
    plist = tmp_path / "agent.plist"
    plist.write_text("")
    hexbin = tmp_path / "hex"
    hexbin.write_text("")
    monkeypatch.setattr(ctl, "_run", fake.run)
    monkeypatch.setattr(ctl, "PLIST", plist)
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


def test_off_reports_hex_busy_and_leaves_it_running(mac, capsys):
    mac.hex_busy = True
    assert ctl.main(["off"]) == 1
    out = capsys.readouterr()
    assert "Hex está ditando" in out.err
    assert not mac.loaded and mac.hex_running


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
    ctl.PLIST.unlink()
    assert ctl.main(["on"]) == 1
    assert "install.sh" in capsys.readouterr().err


def test_unknown_command(mac, capsys):
    assert ctl.main(["talvez"]) == 2
    assert capsys.readouterr().err.strip() == ctl.USO
