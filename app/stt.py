"""Speech-to-text: record a fixed window from the mic, transcribe locally.

Uses faster-whisper (local, no API key, no per-request cost) — a good
default for a college project. Swap WHISPER_MODEL_SIZE in config.py for
a bigger/smaller model if accuracy or speed need tuning.
"""
import tempfile
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as write_wav

from app.config import RECORD_SECONDS, SAMPLE_RATE, WHISPER_MODEL_SIZE

_model = None  # lazy-loaded singleton, loading the model takes a few seconds


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def record_audio(seconds: int = RECORD_SECONDS) -> Path:
    """Record `seconds` of audio from the default mic, return a temp wav path."""
    print(f"Recording for {seconds}s... speak now.")
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    tmp = Path(tempfile.mktemp(suffix=".wav"))
    write_wav(tmp, SAMPLE_RATE, audio)
    return tmp


def transcribe_file(path: Path) -> str:
    """Transcribe an existing wav/mp3/etc. file to text."""
    model = _get_model()
    segments, _info = model.transcribe(str(path))
    return " ".join(seg.text.strip() for seg in segments).strip()


def record_and_transcribe(seconds: int = RECORD_SECONDS) -> str:
    path = record_audio(seconds)
    try:
        return transcribe_file(path)
    finally:
        path.unlink(missing_ok=True)
