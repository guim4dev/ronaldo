"""End-of-dictation logic, driven by real Silero VAD on macOS TTS audio."""

import subprocess
import sys
from pathlib import Path
import wave

import numpy as np
import pytest

from ronaldo.detector import CHUNK, SAMPLE_RATE, VoiceActivity
from ronaldo.listener import MODELS, Config, Listener

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="needs macOS say/afconvert")


def tts(tmp_path, text: str, voice: str = "Luciana") -> np.ndarray:
    aiff, wav = tmp_path / "s.aiff", tmp_path / "s.wav"
    subprocess.run(["say", "-v", voice, "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    with wave.open(str(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16)


def room_noise(seconds: float, seed: int = 0) -> np.ndarray:
    return (np.random.default_rng(seed).normal(0, 60, int(seconds * SAMPLE_RATE))).astype(np.int16)


def chunks(audio: np.ndarray):
    return (audio[i : i + CHUNK] for i in range(0, len(audio) - CHUNK + 1, CHUNK))


@pytest.fixture
def listener():
    lst = Listener.__new__(Listener)  # skip the wake word model: only VAD is exercised
    lst.cfg = Config(routes=[])
    lst.vad = VoiceActivity(MODELS)
    return lst


def consumed_seconds(lst, audio):
    n = 0

    def counting():
        nonlocal n
        for c in chunks(audio):
            n += 1
            yield c

    reason = lst._record_until_silence(counting())
    return reason, n * CHUNK / SAMPLE_RATE


def test_stops_about_two_seconds_after_speech_ends(listener, tmp_path):
    speech = tts(tmp_path, "Escreve um teste pra mim, por favor, e roda a suíte inteira.")
    audio = np.concatenate([room_noise(0.5), speech, room_noise(6)])
    reason, at = consumed_seconds(listener, audio)
    speech_end = (0.5 * SAMPLE_RATE + len(speech)) / SAMPLE_RATE
    assert reason == "silence"
    assert speech_end + 1.5 <= at <= speech_end + 2.6


def test_short_pause_mid_sentence_does_not_end_it(listener, tmp_path):
    a = tts(tmp_path, "Primeira parte da frase")
    b = tts(tmp_path, "e aqui a segunda parte")
    audio = np.concatenate([a, room_noise(1.0, 1), b, room_noise(6, 2)])
    reason, at = consumed_seconds(listener, audio)
    assert reason == "silence"
    assert at > (len(a) + SAMPLE_RATE + len(b)) / SAMPLE_RATE  # kept listening through the 1 s pause


def test_gives_up_when_nothing_is_said(listener):
    reason, at = consumed_seconds(listener, room_noise(20))
    assert reason == "no_speech"
    assert at == pytest.approx(Config().no_speech_seconds, abs=0.1)


def test_hard_cap(listener, tmp_path):
    listener.cfg.max_seconds = 3
    speech = tts(tmp_path, "Isso aqui é uma frase bem comprida que continua falando sem parar por bastante tempo mesmo")
    reason, at = consumed_seconds(listener, np.concatenate([speech, room_noise(3)]))
    assert reason == "max"
    assert at == pytest.approx(3, abs=0.1)


def test_config_ignores_unknown_keys(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('silence_seconds = 3.5\nbogus = 1\n')
    cfg = Config.load(p)
    assert cfg.silence_seconds == 3.5 and cfg.routes[0].threshold == 0.5


def test_reads_from_the_live_audio_queue(listener, tmp_path):
    """The real path: no iterator passed, chunks come from the mic queue."""
    import queue

    listener.audio = queue.Queue()
    speech = tts(tmp_path, "Uma frase curta.")
    for c in chunks(np.concatenate([speech, room_noise(4)])):
        listener.audio.put(c)
    assert listener._record_until_silence() == "silence"


def test_hex_is_stopped_even_if_recording_crashes(listener, monkeypatch):
    """A crash mid-recording must not leave Hex recording forever."""
    from ronaldo import hexcli

    calls = []
    monkeypatch.setattr(hexcli, "ensure_running", lambda: True)
    monkeypatch.setattr(hexcli, "ensure_language", lambda lang: True)
    monkeypatch.setattr(hexcli, "start_dictation", lambda: calls.append("start") or True)
    monkeypatch.setattr(hexcli, "stop_and_transcribe", lambda: calls.append("stop") or "texto")

    def boom(*a, **k):
        raise RuntimeError("mic sumiu")

    monkeypatch.setattr(listener, "_record_until_silence", boom)
    with pytest.raises(RuntimeError):
        listener._dictate(__import__('ronaldo.listener', fromlist=['Route']).Route(model='x.onnx'))
    assert calls == ["start", "stop"]


def test_only_one_listener_can_run(tmp_path):
    """A second instance (e.g. the app double-clicked in Finder) must not listen too."""
    import subprocess, sys

    from ronaldo.listener import single_instance

    lock = tmp_path / "ronaldo.lock"
    held = single_instance(lock)
    assert held is not None
    code = "import sys; from pathlib import Path; from ronaldo.listener import single_instance; sys.exit(0 if single_instance(Path(sys.argv[1])) is None else 1)"
    assert subprocess.run([sys.executable, "-c", code, str(lock)], cwd=Path(__file__).parent.parent).returncode == 0
    held.close()
    assert subprocess.run([sys.executable, "-c", code, str(lock)], cwd=Path(__file__).parent.parent).returncode == 1
