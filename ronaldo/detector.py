"""Wake word + voice activity detection with nothing but onnxruntime.

Reimplements openWakeWord's streaming feature pipeline (melspectrogram ->
Google speech_embedding -> small classifier) so we don't import the
openwakeword package, whose scipy/sklearn dependencies cost ~150 MB of RAM.
The arithmetic mirrors openwakeword 0.4.0 `utils.AudioFeatures` exactly, so
any openWakeWord-compatible model (input [1, 16, 96]) works here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort

CHUNK = 1280  # 80 ms @ 16 kHz: one embedding per chunk
SAMPLE_RATE = 16000
_MEL_WINDOW = 76
_MEL_CONTEXT = 160 * 3  # extra samples so streaming mel frames line up
_WARMUP = 5  # openWakeWord zeroes the first 5 predictions after a reset


def _session(path: Path) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.enable_cpu_mem_arena = False
    opts.log_severity_level = 3
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


class WakeWord:
    def __init__(self, model: Path, models_dir: Path):
        self._mel = _session(models_dir / "melspectrogram.onnx")
        self._emb = _session(models_dir / "embedding_model.onnx")
        self._clf = _session(model)
        self._n_features = self._clf.get_inputs()[0].shape[1]
        self.reset()

    def reset(self) -> None:
        self._raw = np.zeros(0, dtype=np.int16)
        self._mels = np.ones((_MEL_WINDOW, 32), dtype=np.float32)
        self._features = self._embed_clip(np.zeros(SAMPLE_RATE * 10, dtype=np.int16))
        self._seen = 0

    def _melspec(self, audio: np.ndarray) -> np.ndarray:
        out = self._mel.run(None, {"input": audio.astype(np.float32)[None, :]})[0]
        return np.squeeze(out) / 10 + 2

    def _embed_clip(self, audio: np.ndarray) -> np.ndarray:
        mels = self._melspec(audio)
        windows = [mels[i : i + _MEL_WINDOW] for i in range(0, len(mels), 8) if len(mels[i : i + _MEL_WINDOW]) == _MEL_WINDOW]
        batch = np.asarray(windows, dtype=np.float32)[..., None]
        return self._emb.run(None, {"input_1": batch})[0].squeeze()

    def predict(self, chunk: np.ndarray) -> float:
        """Feed exactly one CHUNK of int16 audio; return the wake word score (0..1)."""
        self._raw = np.concatenate([self._raw, chunk])[-(CHUNK + _MEL_CONTEXT) :]
        self._mels = np.vstack([self._mels, self._melspec(self._raw)])[-970:]
        window = self._mels[-_MEL_WINDOW:].astype(np.float32)[None, :, :, None]
        emb = self._emb.run(None, {"input_1": window})[0].squeeze()
        self._features = np.vstack([self._features, emb])[-120:]
        x = self._features[-self._n_features :][None].astype(np.float32)
        score = float(self._clf.run(None, {self._clf.get_inputs()[0].name: x})[0].squeeze())
        self._seen += 1
        return 0.0 if self._seen <= _WARMUP else score


class VoiceActivity:
    """Silero VAD (the v3/v4 model shipped with openWakeWord)."""

    def __init__(self, models_dir: Path):
        self._vad = _session(models_dir / "silero_vad.onnx")
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def speech_prob(self, chunk: np.ndarray, frame: int = 640) -> float:
        probs = []
        for i in range(0, len(chunk), frame):
            x = (chunk[i : i + frame] / 32767).astype(np.float32)[None, :]
            out, self._h, self._c = self._vad.run(None, {"input": x, "h": self._h, "c": self._c, "sr": self._sr})
            probs.append(float(out[0][0]))
        return max(probs)
