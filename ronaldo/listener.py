"""Say a wake word -> Hex records -> silence ends it -> the route decides what happens.

A route either types the text into the focused app (+ Enter) or hands it to an
agent command (fire and forget, reply pushed as a notification).
"""

from __future__ import annotations

import logging
import queue
import signal
import sys
import time
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np
import sounddevice as sd

from . import agent, hexcli, macos
from .detector import CHUNK, SAMPLE_RATE, VoiceActivity, WakeWord

log = logging.getLogger("ronaldo")

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
CONFIG = Path.home() / ".config" / "ronaldo" / "config.toml"


ACTIONS = ("type", "command")


@dataclass
class Route:
    model: str  # file in models/ or an absolute path
    action: str = "type"  # "type" into the focused app, or run "command"
    command: list[str] = field(default_factory=list)  # argv; "{text}" is replaced, else text goes to stdin
    threshold: float = 0.5  # wake word score that triggers
    press_enter: bool = True  # type: press Return after pasting
    notify: bool = True  # command: push the agent's reply as a notification
    timeout_seconds: float = 900  # command: give up on the agent after this long
    name: str = ""

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"route {self.model}: action must be one of {ACTIONS}, got {self.action!r}")
        if self.action == "command" and not self.command:
            raise ValueError(f"route {self.model}: action 'command' needs a command")
        self.name = self.name or self.model_path().stem

    def model_path(self) -> Path:
        p = Path(self.model).expanduser()
        return p if p.is_absolute() else MODELS / p


@dataclass
class Config:
    routes: list[Route] = field(default_factory=lambda: [Route(model="ronaldo_ptbr.onnx")])
    silence_seconds: float = 2.0  # quiet time that ends the dictation
    no_speech_seconds: float = 6.0  # give up if nothing is said after the wake word
    max_seconds: float = 60.0  # hard cap per dictation
    vad_threshold: float = 0.5  # Silero speech probability counted as speech
    cooldown_seconds: float = 1.5  # ignore wake words right after a dictation
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
        kw = {k: v for k, v in data.items() if k in known}
        if "routes" in kw:
            kw["routes"] = [Route(**r) for r in kw["routes"]]
        return cls(**kw)


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
        self.routes = {r.name: r for r in cfg.routes}
        self.wake = WakeWord([r.model_path() for r in cfg.routes], MODELS)
        self.path = agent.login_path() if any(r.action == "command" for r in cfg.routes) else ""
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

    def _pick(self, scores: dict[str, float]) -> Route | None:
        hits = [(s, self.routes[n]) for n, s in scores.items() if s >= self.routes[n].threshold]
        return max(hits, key=lambda h: h[0])[1] if hits else None

    def _dictate(self, route: Route) -> None:
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
            log.info("sem fala; nada feito")
            return
        if route.action == "command":
            agent.dispatch(route.command, text, path=self.path, timeout=route.timeout_seconds, notify_reply=route.notify, name=route.name)
            return
        log.info("colando %d caracteres%s", len(text), " + Enter" if route.press_enter else "")
        macos.type_and_submit(text, submit=route.press_enter)

    def run(self) -> None:
        cfg = self.cfg
        for r in cfg.routes:
            log.info("ouvindo '%s' → %s (limiar %.2f)", r.name, r.action if r.action == "type" else r.command[0], r.threshold)
        if any(r.action == "type" for r in cfg.routes) and not macos.is_trusted_for_accessibility():
            log.warning("sem permissão de Acessibilidade: o texto não vai ser colado nem o Enter enviado")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=self._on_audio):
            while True:
                scores = self.wake.scores(self.audio.get())
                route = self._pick(scores)
                if route is None or time.monotonic() < self.quiet_until:
                    continue
                log.info("wake word '%s' (nota %.2f)", route.name, scores[route.name])
                try:
                    self._dictate(route)
                except Exception:
                    log.exception("falha no ditado")
                self._drain()
                self.wake.reset()
                self.quiet_until = time.monotonic() + cfg.cooldown_seconds


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    cfg = Config.load()
    missing = [str(r.model_path()) for r in cfg.routes if not r.model_path().exists()]
    if missing:
        log.error("modelo não encontrado: %s", ", ".join(missing))
        sys.exit(1)
    Listener(cfg).run()


if __name__ == "__main__":
    main()
