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

from app.config import RECORD_SECONDS, SAMPLE_RATE, WHISPER_MODEL_SIZE, WHISPER_MULTILINGUAL_MODEL_SIZE

_models: dict[str, object] = {}  # lazy-loaded per size, loading a model takes a few seconds


def _get_model(size: str):
    if size not in _models:
        from faster_whisper import WhisperModel

        _models[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _models[size]


def record_audio(seconds: int = RECORD_SECONDS) -> Path:
    """Record `seconds` of audio from the default mic, return a temp wav path."""
    print(f"Recording for {seconds}s... speak now.")
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    tmp = Path(tempfile.mktemp(suffix=".wav"))
    write_wav(tmp, SAMPLE_RATE, audio)
    return tmp


def transcribe_with_info(path: Path, multilingual: bool = False) -> tuple[str, str]:
    """Transcribe an audio file. Returns (text, detected_language_code).

    `multilingual` uses a larger model and lets Whisper detect the language,
    returning the text in the language that was spoken (Hindi in Devanagari,
    or romanized Hinglish). It is *not* translated here: Whisper's own
    translate task garbles Hindi, so nl2sql.translate_question has the LLM do
    that step, with the table schema to fix mishearings.
    """
    model = _get_model(WHISPER_MULTILINGUAL_MODEL_SIZE if multilingual else WHISPER_MODEL_SIZE)
    segments, info = model.transcribe(str(path))
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text, info.language


def transcribe_file(path: Path) -> str:
    """Transcribe an existing wav/mp3/etc. file to text."""
    return transcribe_with_info(path)[0]


def record_and_transcribe(seconds: int = RECORD_SECONDS) -> str:
    path = record_audio(seconds)
    try:
        return transcribe_file(path)
    finally:
        path.unlink(missing_ok=True)
