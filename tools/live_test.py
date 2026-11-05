"""Live check: prints the wake word score while you talk, plus peak RAM.

Usage: uv run python tools/live_test.py [seconds] [model.onnx]
"""
import resource
import sys
import time
from pathlib import Path

import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ronaldo.detector import CHUNK, WakeWord  # noqa: E402
from ronaldo.listener import Config, MODELS  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20
model = Path(sys.argv[2]) if len(sys.argv) > 2 else Config.load().model_path()
ww = WakeWord(model, MODELS)
print(f"Modelo {model.name}. Fala a wake word algumas vezes e converse normal ({secs:.0f}s)...", flush=True)
peaks, end = [], time.time() + secs
with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=CHUNK) as s:
    while time.time() < end:
        chunk, _ = s.read(CHUNK)
        score = ww.predict(chunk[:, 0])
        if score > 0.05:
            print(f"  {time.strftime('%H:%M:%S')}  nota={score:.2f} {'#' * int(score * 40)}", flush=True)
        peaks.append(score)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
print(f"\nmaior nota: {max(peaks):.2f} | frames acima de 0.5: {sum(p > 0.5 for p in peaks)} | RAM máx: {rss:.0f} MB")
