"""Persistent non-activating floating feedback panel."""
from __future__ import annotations
import atexit, json, logging, os, subprocess, sys, tempfile, threading, time
from pathlib import Path
log=logging.getLogger("ronaldo.hud")
_SCRIPT=Path(__file__).with_name("hud.js")
_STATE=Path.home()/"Library/Caches/ronaldo/hud.json"
_lock=threading.RLock(); _seq=0; _daemon=None
def begin():
 global _seq
 with _lock: _seq+=1; return _seq
def _write_state(payload):
 _STATE.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix="hud-",suffix=".tmp",dir=_STATE.parent)
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False); f.flush(); os.fsync(f.fileno())
  os.replace(name,_STATE)
 finally:
  try: os.unlink(name)
  except FileNotFoundError: pass
def start():
 global _daemon
 try:
  with _lock:
   if _daemon is not None and _daemon.poll() is None: return
   if _daemon is not None:
    try: _daemon.wait(timeout=0)
    except Exception: pass
   _STATE.parent.mkdir(parents=True,exist_ok=True)
   _daemon=subprocess.Popen(["osascript","-l","JavaScript",str(_SCRIPT),str(_STATE)],stdout=subprocess.DEVNULL,stderr=sys.stderr)
 except Exception: log.exception("não foi possível iniciar daemon do HUD")
def stop():
 global _daemon
 try:
  with _lock:
   proc,_daemon=_daemon,None
   if proc is None: return
   try:
    if proc.poll() is None: proc.terminate()
    try: proc.wait(timeout=1)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=1)
   except Exception: log.exception("erro encerrando daemon do HUD")
 except Exception: log.exception("erro encerrando HUD")
atexit.register(stop)
def show(title,body,kind="info",seconds=6,req_id=None):
 try:
  with _lock:
   if req_id is not None and req_id!=_seq: return
   start()
   if _daemon is None or _daemon.poll() is not None: return
   _write_state({"id":req_id if req_id is not None else begin(),"title":title,"body":body,"kind":kind,"seconds":seconds})
 except Exception: log.exception("não foi possível mostrar HUD")
def main(argv=None):
 args=list(sys.argv[1:] if argv is None else argv)
 if len(args)<2: print("uso: python -m ronaldo.hud <titulo> <corpo> [kind] [segundos]",file=sys.stderr); return 2
 title,body=args[:2]; kind=args[2] if len(args)>2 else "info"; seconds=float(args[3]) if len(args)>3 else 6
 start(); show(title,body,kind,seconds); time.sleep(seconds+1); stop(); return 0
if __name__=="__main__": raise SystemExit(main())
