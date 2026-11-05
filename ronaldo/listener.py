"""Say the wake word -> Hex records -> silence ends it -> text is pasted and Enter pressed."""

from __future__ import annotations

import logging
import queue
import signal
import sys
import time
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import sounddevice as sd

from . import hexcli, macos
from .detector import CHUNK, SAMPLE_RATE, VoiceActivity, WakeWord

log = logging.getLogger("ronaldo")

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
CONFIG = Path.home() / ".config" / "ronaldo" / "config.toml"


@dataclass
class Config:
    model: str = "ronaldo_ptbr.onnx"  # file in models/ or an absolute path
    threshold: float = 0.5  # wake word score that triggers
    silence_seconds: float = 2.0  # quiet time that ends the dictation
    no_speech_seconds: float = 6.0  # give up if nothing is said after the wake word
    max_seconds: float = 60.0  # hard cap per dictation
    vad_threshold: float = 0.5  # Silero speech probability counted as speech
    press_enter: bool = True
    cooldown_seconds: float = 1.5  # ignore the wake word right after a dictation
    language: str = "auto"  # Hex transcription language; "auto" = macOS preferred language

    def resolved_language(self) -> str:
        return system_language() if self.language == "auto" else self.language

    @classmethod
    def load(cls, path: Path = CONFIG) -> "Config":
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        for k in set(data) - known:
            log.warning("config: chave desconhecida ignorada: %s", k)
        return cls(**{k: v for k, v in data.items() if k in known})

    def model_path(self) -> Path:
        p = Path(self.model).expanduser()
        return p if p.is_absolute() else MODELS / p


def _apple_languages() -> list[str]:
    import subprocess

    out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True).stdout
    return [s.strip().strip('",') for s in out.splitlines() if s.strip() not in ("(", ")", "")]


def system_language() -> str:
    """macOS's preferred language as Hex expects it: "pt-BR" -> "pt"."""
    langs = _apple_languages()
    return langs[0].split("-")[0].lower() if langs else "en"


class Listener:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.wake = WakeWord(cfg.model_path(), MODELS)
        self.vad = VoiceActivity(MODELS)
        self.audio: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self.quiet_until = 0.0

    def _on_audio(self, data, frames, t, status) -> None:
        try:
            self.audio.put_nowait(data[:, 0].copy())
        except queue.Full:
            pass  # we're busy transcribing; dropping audio is fine

    def _drain(self) -> None:
        while not self.audio.empty():
            self.audio.get_nowait()

    def _record_until_silence(self, chunks=None) -> str:
        """Consume audio until the speaker stops; returns why it ended.

        Time is counted in audio chunks (80 ms each), not wall clock, so the
        behaviour is identical when fed from a file in tests.
        """
        cfg = self.cfg
        source = chunks if chunks is not None else self._live_chunks()
        self.vad.reset()
        step = CHUNK / SAMPLE_RATE
        elapsed, last_speech = 0.0, None
        for chunk in source:
            elapsed += step
            if self.vad.speech_prob(chunk) >= cfg.vad_threshold:
                last_speech = elapsed
            if last_speech is None and elapsed >= cfg.no_speech_seconds:
                return "no_speech"
            if last_speech is not None and elapsed - last_speech >= cfg.silence_seconds:
                return "silence"
            if elapsed >= cfg.max_seconds:
                return "max"
        return "eof"

    def _live_chunks(self):
        while True:
            yield self.audio.get()

    def _dictate(self) -> None:
        if not hexcli.ensure_running():
            return
        hexcli.ensure_language(self.cfg.resolved_language())  # best effort: dictate anyway
        if not hexcli.start_dictation():
            return
        log.info("gravando…")
        try:
            log.info("fim da gravação: %s", self._record_until_silence())
        finally:
            text = hexcli.stop_and_transcribe()  # never leave Hex recording
        if not text:
            log.info("sem fala; nada colado")
            return
        log.info("colando %d caracteres%s", len(text), " + Enter" if self.cfg.press_enter else "")
        macos.type_and_submit(text, submit=self.cfg.press_enter)

    def run(self) -> None:
        cfg = self.cfg
        log.info("ouvindo '%s' (limiar %.2f)", cfg.model_path().stem, cfg.threshold)
        if not macos.is_trusted_for_accessibility():
            log.warning("sem permissão de Acessibilidade: o texto não vai ser colado nem o Enter enviado")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=self._on_audio):
            while True:
                chunk = self.audio.get()
                score = self.wake.predict(chunk)
                if score < cfg.threshold or time.monotonic() < self.quiet_until:
                    continue
                log.info("wake word (nota %.2f)", score)
                try:
                    self._dictate()
                except Exception:
                    log.exception("falha no ditado")
                self._drain()
                self.wake.reset()
                self.quiet_until = time.monotonic() + cfg.cooldown_seconds


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    cfg = Config.load()
    if not cfg.model_path().exists():
        log.error("modelo não encontrado: %s", cfg.model_path())
        sys.exit(1)
    Listener(cfg).run()


if __name__ == "__main__":
    main()
