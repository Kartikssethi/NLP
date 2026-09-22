"""Central configuration for the voice-to-SQL project.

Keep this file boring: plain constants, no logic. Override any of these
with environment variables of the same name if you need to.
"""
import os

# --- Database -----------------------------------------------------------
DB_PATH = os.environ.get("NLP_DB_PATH", "data/nlp.db")

# --- Speech-to-text -------------------------------------------------------
# faster-whisper model size: tiny / base / small / medium / large-v3
# "base" is a good speed/accuracy tradeoff on a laptop CPU.
WHISPER_MODEL_SIZE = os.environ.get("NLP_WHISPER_MODEL", "base")
RECORD_SECONDS = int(os.environ.get("NLP_RECORD_SECONDS", "30"))
SAMPLE_RATE = 16000

# --- NL -> SQL fallback (Ollama) ------------------------------------------
# Only used when the rule-based parser can't confidently handle the utterance.
OLLAMA_MODEL = os.environ.get("NLP_OLLAMA_MODEL", "llama3.1")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
