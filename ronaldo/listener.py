"""Say a wake word -> Hex records -> silence ends it -> the route decides what happens.

A route either types the text into the focused app (+ Enter), hands it to an
agent command (fire and forget, reply pushed as a notification), or plays a
local sound when the gate accepts the shout (no dictation, no Hex).
"""

from __future__ import annotations

import fcntl
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

from . import agent, hexcli, macos, som as som_mod, voz
from . import hud as agent_hud
from .detector import CHUNK, SAMPLE_RATE, VoiceActivity, WakeWord
from .grito import PortaoGrito

log = logging.getLogger("ronaldo")

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
CONFIG = Path.home() / ".config" / "ronaldo" / "config.toml"
LOCK = Path.home() / "Library" / "Caches" / "ronaldo.lock"


ACTIONS = ("type", "command", "som")


@dataclass
class Route:
    model: str  # file in models/ or an absolute path
    action: str = "type"  # "type" into the focused app, "command" for an agent, "som" for a local sound
    command: list[str] = field(default_factory=list)  # argv; "{text}" is replaced, else text goes to stdin
    threshold: float = 0.5  # wake word score that triggers
    press_enter: bool = True  # type: press Return after pasting
    notify: bool = True  # command: push the agent's reply as a notification
    hud: bool = True  # command: show floating feedback
    timeout_seconds: float = 900  # command: give up on the agent after this long
    name: str = ""
    atalhos: list[dict] = field(default_factory=list)
    voz: bool = False  # command: envia com --id e fala a resposta do rei (modo voz ligado)
    intervalo_seconds: float = 8.0  # som: mínimo entre disparos da mesma rota
    grito_db_acima: float = 10.0  # som: nível acima da fala normal que libera o grito

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"route {self.model}: action must be one of {ACTIONS}, got {self.action!r}")
        if self.action in ("command", "som") and not self.command:
            raise ValueError(f"route {self.model}: action {self.action!r} needs a command")
        self.name = self.name or self.model_path().stem
        if self.atalhos and self.action != "command":
            raise ValueError("atalhos só são válidos em rotas command")
        if self.voz and self.action != "command":
            raise ValueError("voz só é válida em rotas command")
        for item in self.atalhos:
            if not item.get("palavras"):
                raise ValueError("atalho precisa de palavras")
            if "comando" in item:
                cmd = item["comando"]
                if "terminal" in item:
                    raise ValueError("atalho tem terminal ou comando, não os dois")
                if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) and c for c in cmd)):
                    raise ValueError("comando do atalho precisa ser uma lista de strings")
                mp = item.get("max_palavras", 1)
                if isinstance(mp, bool) or not isinstance(mp, int) or mp < 1:
                    raise ValueError("max_palavras precisa ser um inteiro >= 1")
            elif not item.get("terminal"):
                raise ValueError("atalho precisa de terminal ou comando")

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
    voz: dict = field(default_factory=dict)  # [voz]: motores e volume, lidos por voz.py

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
            seen = set()
            for route in kw["routes"]:
                for shortcut in route.atalhos:
                    for word in shortcut["palavras"]:
                        from .atalhos import _normalizar
                        normalized = _normalizar(word)
                        if normalized in seen:
                            raise ValueError(f"palavra de atalho repetida: {word}")
                        seen.add(normalized)
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
    som: som_mod.SomPlayer | None = None  # __new__ em testes não passa pelo __init__

    def __init__(self, cfg: Config, *, wake=None, vad=None, som_player=None):
        self.cfg = cfg
        self.routes = {r.name: r for r in cfg.routes}
        self.wake = wake if wake is not None else WakeWord([r.model_path() for r in cfg.routes], MODELS)
        self.path = agent.login_path() if any(r.action in ("command", "som") for r in cfg.routes) else ""
        self.vad = vad if vad is not None else VoiceActivity(MODELS)
        self.som = som_player if som_player is not None else som_mod.padrao()
        self.grito = PortaoGrito() if any(r.action == "som" for r in cfg.routes) else None
        self.audio: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self.quiet_until = 0.0
        self._chunks = 0
        self._ultimo_som: dict[str, int] = {}

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
        use_hud = route.action == "command" and route.hud
        req_id = agent_hud.begin() if use_hud else None
        if self.som is not None:
            self.som.stop()  # o ditado tem prioridade: o som para antes do Hex
        voz.parar()  # a wake word corta qualquer fala em andamento
        voz.marcar_gravando(True)
        try:
            if not hexcli.ensure_running():
                if use_hud: agent_hud.show("⚠️ Não entendi", "Hex não está disponível.", "warn", 5, req_id)
                return
            hexcli.ensure_language(self.cfg.resolved_language())
            if not hexcli.start_dictation():
                if use_hud: agent_hud.show("⚠️ Não entendi", "Não consegui iniciar a gravação.", "warn", 5, req_id)
                return
            log.info("gravando…")
            try:
                reason = self._record_until_silence()
                log.info("fim da gravação: %s", reason)
            finally:
                text = hexcli.stop_and_transcribe()
            if not text:
                log.info("sem fala; nada feito")
                if use_hud: agent_hud.show("⚠️ Não entendi", "Não detectei fala.", "warn", 5, req_id)
                return
            if route.action == "command":
                if use_hud:
                    agent_hud.show("🎙️ Ronaldo ouviu", agent.summarize(text) + " — enviando…", "info", 6, req_id)
                agent.dispatch(route.command, text, path=self.path, timeout=route.timeout_seconds, notify_reply=route.notify, name=route.name, hud=use_hud, req_id=req_id, atalhos=route.atalhos, voz=route.voz)
                return
            log.info("colando %d caracteres%s", len(text), " + Enter" if route.press_enter else "")
            macos.type_and_submit(text, submit=route.press_enter)
        except Exception as exc:
            if use_hud:
                agent_hud.show("⚠️ Não entendi", agent.summarize(str(exc)) or "Falha no ditado.", "warn", 5, req_id)
            raise
        finally:
            voz.marcar_gravando(False)

    def processar_chunk(self, chunk: np.ndarray) -> Route | None:
        """Feed one chunk; a `som` route fires here and never starts a dictation.

        Returns the route that should dictate, or None.
        """
        self._chunks += 1
        if self.grito is not None:
            fala = self.vad.speech_prob(chunk) >= self.cfg.vad_threshold
            self.grito.observar(chunk, fala)
        scores = self.wake.scores(chunk)
        route = self._pick(scores)
        if route is None or time.monotonic() < self.quiet_until:
            return None
        if route.action == "som":
            self._tentar_som(route, scores[route.name])
            return None
        log.info("wake word '%s' (nota %.2f)", route.name, scores[route.name])
        return route

    def _tentar_som(self, route: Route, nota: float) -> bool:
        """Passa pelo portão de grito, respeita o intervalo e toca o comando."""
        if self.grito is None or self.som is None:
            return False
        decisao = self.grito.avaliar(nota, route.grito_db_acima)
        if not decisao.liberado:
            return False
        passo = CHUNK / SAMPLE_RATE
        ultimo = self._ultimo_som.get(route.name)
        if ultimo is not None and (self._chunks - ultimo) * passo < route.intervalo_seconds:
            log.info("grito '%s': intervalo de %.1f s ainda não passou", route.name, route.intervalo_seconds)
            return False
        if not self.som.tocar(route.command, path=self.path or som_mod.PATH_PADRAO, nome=route.name):
            return False
        self._ultimo_som[route.name] = self._chunks
        return True

    def run(self) -> None:
        cfg = self.cfg
        if any(r.action == "command" and r.hud for r in cfg.routes):
            import atexit
            agent_hud.start()
            atexit.register(agent_hud.stop)
        for r in cfg.routes:
            log.info("ouvindo '%s' → %s (limiar %.2f)", r.name, r.action if r.action == "type" else r.command[0], r.threshold)
        if any(r.action == "type" for r in cfg.routes) and not macos.is_trusted_for_accessibility():
            log.warning("sem permissão de Acessibilidade: o texto não vai ser colado nem o Enter enviado")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=self._on_audio):
            while True:
                route = self.processar_chunk(self.audio.get())
                if route is None:
                    continue
                try:
                    self._dictate(route)
                except Exception:
                    log.exception("falha no ditado")
                self._drain()
                self.wake.reset()
                self.quiet_until = time.monotonic() + cfg.cooldown_seconds


def single_instance(path: Path = LOCK):
    """Hold an exclusive lock for this process's lifetime; None if another listener has it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    lock = single_instance()
    if lock is None:
        log.warning("outro Ronaldo já está ouvindo; saindo")
        sys.exit(0)
    cfg = Config.load()
    missing = [str(r.model_path()) for r in cfg.routes if not r.model_path().exists()]
    if missing:
        log.error("modelo não encontrado: %s", ", ".join(missing))
        sys.exit(1)
    Listener(cfg).run()


if __name__ == "__main__":
    main()
