"""Live check: prints the wake word score while you talk, plus peak RAM.

Each line also shows the shout gate's level (dBFS) and speech reference, so the
route can be calibrated by ear. Nothing is written to disk.

Usage: uv run python tools/live_test.py [seconds] [model.onnx]
"""
import resource
import sys
import time
from pathlib import Path

import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ronaldo.detector import CHUNK, VoiceActivity, WakeWord  # noqa: E402
from ronaldo.grito import PortaoGrito  # noqa: E402
from ronaldo.listener import Config, MODELS  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20
model = Path(sys.argv[2]) if len(sys.argv) > 2 else Config.load().routes[0].model_path()
ww = WakeWord(model, MODELS)
vad = VoiceActivity(MODELS)
gate = PortaoGrito()
print(f"Modelo {model.name}. Fala a wake word algumas vezes e converse normal ({secs:.0f}s)...", flush=True)
peaks, end = [], time.time() + secs
with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=CHUNK) as s:
    while time.time() < end:
        chunk, _ = s.read(CHUNK)
        audio = chunk[:, 0]
        gate.observar(audio, vad.speech_prob(audio) >= 0.5)
        score = ww.predict(audio)
        if score > 0.05:
            referencia = "—" if gate.referencia is None else f"{gate.referencia:6.1f} dB"
            print(
                f"  {time.strftime('%H:%M:%S')}  nota={score:.2f} nível={gate.nivel:6.1f} dBFS"
                f" ref={referencia} {'#' * int(score * 40)}",
                flush=True,
            )
        peaks.append(score)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
print(f"\nmaior nota: {max(peaks):.2f} | frames acima de 0.5: {sum(p > 0.5 for p in peaks)} | RAM máx: {rss:.0f} MB")
