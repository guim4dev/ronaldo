"""Ao vivo: mostra se um grito disparia a rota `som`, sem gravar nem tocar nada.

Usa o modelo da rota `som` do config (ou o caminho passado) e o portão de volume.
Nada é persistido: referência e nível vivem só na memória.

Usage: uv run python tools/grito_ao_vivo.py [seconds] [model.onnx]
"""
import sys
import time
from pathlib import Path

import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ronaldo.detector import CHUNK, VoiceActivity, WakeWord  # noqa: E402
from ronaldo.grito import PortaoGrito  # noqa: E402
from ronaldo.listener import Config, MODELS  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
cfg = Config.load()
rota = next((r for r in cfg.routes if r.action == "som"), None)

if len(sys.argv) > 2:
    model = Path(sys.argv[2]).expanduser()
elif rota is not None:
    model = rota.model_path()
else:
    sys.exit("nenhuma rota som no config; passe o modelo: grito_ao_vivo.py [segundos] [modelo.onnx]")

acima_db = rota.grito_db_acima if rota is not None else 10.0
ww = WakeWord(model, MODELS)
vad = VoiceActivity(MODELS)
gate = PortaoGrito()
print(
    f"Modelo {model.name} | grito_db_acima={acima_db:g} dB | {secs:.0f}s. "
    "Grite e converse normal; nada é gravado nem tocado.",
    flush=True,
)
end = time.time() + secs
with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=CHUNK) as s:
    while time.time() < end:
        chunk, _ = s.read(CHUNK)
        audio = chunk[:, 0]
        gate.observar(audio, vad.speech_prob(audio) >= 0.5)
        nota = max(ww.scores(audio).values())
        if nota > 0.05:
            decisao = gate.avaliar(nota, acima_db)
            referencia = "—" if decisao.referencia is None else f"{decisao.referencia:6.1f} dB"
            veredito = "DISPARARIA" if decisao.liberado else "barrado"
            print(
                f"  {time.strftime('%H:%M:%S')}  nota={nota:.2f} nível={decisao.nivel:6.1f} dBFS"
                f" ref={referencia} {veredito}",
                flush=True,
            )
print(f"fim: referência={'—' if gate.referencia is None else f'{gate.referencia:.1f} dB'}")
