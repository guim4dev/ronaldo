"""Our onnxruntime-only detector must score exactly like openwakeword's reference."""

import os
import subprocess
import wave

import numpy as np
import openwakeword
from openwakeword.model import Model

from pathlib import Path

from ronaldo.detector import CHUNK, WakeWord
from ronaldo.listener import MODELS

JARVIS = Path(openwakeword.__file__).parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"


def tts(tmp_path, text, voice="Samantha"):
    aiff, wav = tmp_path / "a.aiff", tmp_path / "a.wav"
    subprocess.run(["say", "-v", voice, "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    with wave.open(str(wav)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    pad = np.zeros(16000, np.int16)
    return np.concatenate([pad, a, pad])


def scores(audio):
    ref, ours = Model(wakeword_model_paths=[str(JARVIS)]), WakeWord(JARVIS, MODELS)
    r, o = [], []
    for i in range(0, len(audio) - CHUNK, CHUNK):
        r.append(list(ref.predict(audio[i : i + CHUNK]).values())[0])
        o.append(ours.predict(audio[i : i + CHUNK]))
    return np.array(r), np.array(o)


def test_matches_reference_on_wake_word(tmp_path):
    r, o = scores(tts(tmp_path, "hey jarvis"))
    assert r.max() > 0.9  # the clip really triggers
    np.testing.assert_allclose(o, r, atol=1e-5)


def test_matches_reference_on_other_speech(tmp_path):
    r, o = scores(tts(tmp_path, "Bom dia, vamos revisar o código amanhã.", voice="Luciana"))
    assert r.max() < 0.5
    np.testing.assert_allclose(o, r, atol=1e-5)


def test_reset_restores_initial_state(tmp_path):
    audio = tts(tmp_path, "hey jarvis")
    ww = WakeWord(JARVIS, MODELS)
    first = [ww.predict(audio[i : i + CHUNK]) for i in range(0, len(audio) - CHUNK, CHUNK)]
    ww.reset()
    second = [ww.predict(audio[i : i + CHUNK]) for i in range(0, len(audio) - CHUNK, CHUNK)]
    assert first == second


def test_several_wake_words_score_like_each_one_alone(tmp_path):
    alexa = JARVIS.with_name("alexa_v0.1.onnx")
    audio = tts(tmp_path, "hey jarvis, alexa")
    both, solo_j, solo_a = WakeWord([JARVIS, alexa], MODELS), WakeWord(JARVIS, MODELS), WakeWord(alexa, MODELS)
    for i in range(0, len(audio) - CHUNK, CHUNK):
        c = audio[i : i + CHUNK]
        s = both.scores(c)
        assert s[JARVIS.stem] == solo_j.predict(c)
        assert s[alexa.stem] == solo_a.predict(c)
