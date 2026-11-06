import json, subprocess
from types import SimpleNamespace
from ronaldo import hud

class Proc:
    def __init__(self,*a,**k): self.args=a; self.running=True; self.killed=False
    def poll(self): return None if self.running else 0
    def wait(self,timeout=None):
        if self.running: raise subprocess.TimeoutExpired("osascript",timeout)
        return 0
    def terminate(self): self.running=False
    def kill(self): self.killed=True; self.running=False

def reset(monkeypatch,tmp_path):
    monkeypatch.setattr(hud,"_STATE",tmp_path/"hud.json")
    monkeypatch.setattr(hud,"_daemon",None); monkeypatch.setattr(hud,"_seq",0)

def test_atomic_json_and_stale_id(monkeypatch,tmp_path):
    reset(monkeypatch,tmp_path); p=Proc(); monkeypatch.setattr(hud.subprocess,"Popen",lambda *a,**k:p)
    hud.begin(); old=hud.begin(); hud.show("old","body",req_id=old-1)
    assert not (tmp_path/"hud.json").exists()
    hud.show("title","body","ok",3,old)
    assert json.loads((tmp_path/"hud.json").read_text())=={"id":old,"title":"title","body":"body","kind":"ok","seconds":3}
    assert not list(tmp_path.glob("*.tmp"))

def test_daemon_restarted_if_dead(monkeypatch,tmp_path):
    reset(monkeypatch,tmp_path); ps=[]; monkeypatch.setattr(hud.subprocess,"Popen",lambda *a,**k:ps.append(Proc()) or ps[-1])
    hud.start(); ps[0].running=False; hud.start(); assert len(ps)==2 and ps[0].poll()==0

def test_stop_kills_stubborn_daemon(monkeypatch,tmp_path):
    reset(monkeypatch,tmp_path); p=Proc(); p.terminate=lambda:None
    monkeypatch.setattr(hud.subprocess,"Popen",lambda *a,**k:p); hud.start(); hud.stop(); assert p.killed

def test_show_swallows_spawn_and_write_errors(monkeypatch,tmp_path):
    reset(monkeypatch,tmp_path); monkeypatch.setattr(hud.subprocess,"Popen",lambda *a,**k:(_ for _ in ()).throw(OSError("spawn"))); hud.show("x","y")
    reset(monkeypatch,tmp_path); monkeypatch.setattr(hud.subprocess,"Popen",lambda *a,**k:Proc())
    monkeypatch.setattr(hud,"_write_state",lambda *_:(_ for _ in ()).throw(OSError("write"))); hud.show("x","y")

def test_main_waits_then_stops(monkeypatch,tmp_path):
    reset(monkeypatch,tmp_path); p=Proc(); monkeypatch.setattr(hud.subprocess,"Popen",lambda *a,**k:p)
    monkeypatch.setattr(hud.time,"sleep",lambda _:None); assert hud.main(["t","b","info","0.1"])==0; assert not p.running

def test_agent_final_hud_and_notify_error(monkeypatch):
    from ronaldo import agent
    calls=[]
    monkeypatch.setattr(agent.subprocess,"run",lambda *a,**k:SimpleNamespace(returncode=0,stdout="Entregue ao rei do Pessoal.",stderr=""))
    monkeypatch.setattr(agent,"notify",lambda *a,**k:(_ for _ in ()).throw(OSError("notify")))
    monkeypatch.setattr(hud,"show",lambda *a,**k:calls.append((a,k)))
    assert agent.run(["corte","falar","{text}"],"fala",path="/bin",timeout=1,notify_reply=True,name="pessoal",hud=True,req_id=8)[0]
    assert calls[-1][0][0] and calls[-1][0][1]=="fala"

def test_agent_error_timeout_and_missing(monkeypatch):
    from ronaldo import agent
    calls=[]; monkeypatch.setattr(hud,"show",lambda *a,**k:calls.append(a))
    monkeypatch.setattr(agent.subprocess,"run",lambda *a,**k:SimpleNamespace(returncode=1,stdout="",stderr="erro"))
    assert not agent.run(["x"],"fala",path="/bin",timeout=1,notify_reply=False,name="r",hud=True)[0]
    monkeypatch.setattr(agent.subprocess,"run",lambda *a,**k:(_ for _ in ()).throw(FileNotFoundError()))
    assert not agent.run(["missing"],"x",path="/bin",timeout=1,notify_reply=False,name="r",hud=True)[0]
    monkeypatch.setattr(agent.subprocess,"run",lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired("x",1)))
    assert not agent.run(["x"],"x",path="/bin",timeout=1,notify_reply=False,name="r",hud=True)[0]
    assert len(calls)==3
