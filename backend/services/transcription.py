"""
Transcription Service
─────────────────────
Two backends depending on language:
  • English              → OpenAI Whisper (whisper-1)
  • Indian languages     → Sarvam AI  (saarika:v2)
    (hi, ta, te, kn, mr, bn, gu, pa, ml, or)

Sarvam AI is purpose-built for Indian languages and gives significantly
better accuracy than Whisper for Hindi/Marathi/Tamil etc.
API docs: https://docs.sarvam.ai/api-reference-docs/speech-to-text-translate
"""

import os
import httpx
from openai import OpenAI
from pydantic_settings import BaseSettings


INDIAN_LANGUAGES = {"hi", "ta", "te", "kn", "mr", "bn", "gu", "pa", "ml", "or"}

SARVAM_LANGUAGE_CODES = {
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "mr": "mr-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
    "pa": "pa-IN",
    "ml": "ml-IN",
    "or": "or-IN",
}


class AISettings(BaseSettings):
    OPENAI_API_KEY: str
    ANTHROPIC_API_KEY: str
    SARVAM_API_KEY: str = ""   # Optional — falls back to Whisper if not set
    
    model_config = {"extra": "ignore", "env_file": ".env"}


ai_settings = AISettings()
openai_client = OpenAI(api_key=ai_settings.OPENAI_API_KEY)


def transcribe_audio(file_path: str, language: str = None) -> str:
    """
    Route to the best transcription engine based on language.
    - Indian languages with Sarvam key → Sarvam AI
    - Everything else → OpenAI Whisper
    """
    lang = (language or "en").lower().strip()

    if lang in INDIAN_LANGUAGES and ai_settings.SARVAM_API_KEY:
        return _transcribe_sarvam(file_path, lang)
    else:
        return _transcribe_whisper(file_path, language)


def _transcribe_whisper(file_path: str, language: str = None) -> str:
    """OpenAI Whisper — reliable for English and mixed-language audio."""
    try:
        with open(file_path, "rb") as audio_file:
            kwargs = {"model": "whisper-1", "file": audio_file}
            if language:
                kwargs["language"] = language
            transcript = openai_client.audio.transcriptions.create(**kwargs)
        return transcript.text
    except Exception as e:
        print(f"[Whisper] Transcription error: {e}")
        raise e


def _transcribe_sarvam(file_path: str, language: str) -> str:
    """
    Sarvam AI saarika:v2 — best-in-class for Indian languages.
    Handles code-mixed speech (e.g., Hinglish) natively.
    API: POST https://api.sarvam.ai/speech-to-text
    """
    lang_code = SARVAM_LANGUAGE_CODES.get(language, "hi-IN")
    try:
        with open(file_path, "rb") as audio_file:
            response = httpx.post(
                "https://api.sarvam.ai/speech-to-text",
                headers={"api-subscription-key": ai_settings.SARVAM_API_KEY},
                files={"file": (os.path.basename(file_path), audio_file, "audio/wav")},
                data={
                    "language_code": lang_code,
                    "model": "saarika:v2",
                    "with_timestamps": "false",
                },
                timeout=60.0,
            )
        response.raise_for_status()
        data = response.json()
        return data.get("transcript", "")
    except httpx.HTTPStatusError as e:
        print(f"[Sarvam] HTTP error {e.response.status_code}: {e.response.text}")
        # Graceful fallback to Whisper
        print("[Sarvam] Falling back to Whisper...")
        return _transcribe_whisper(file_path, language)
    except Exception as e:
        print(f"[Sarvam] Error: {e} — falling back to Whisper")
        return _transcribe_whisper(file_path, language)


def detect_language(text: str) -> str:
    """
    Quick heuristic language detection using character ranges.
    Returns ISO 639-1 code.
    """
    if not text:
        return "en"

    devanagari_chars = sum(1 for c in text if "\u0900" <= c <= "\u097F")
    tamil_chars      = sum(1 for c in text if "\u0B80" <= c <= "\u0BFF")
    telugu_chars     = sum(1 for c in text if "\u0C00" <= c <= "\u0C7F")
    kannada_chars    = sum(1 for c in text if "\u0C80" <= c <= "\u0CFF")
    bengali_chars    = sum(1 for c in text if "\u0980" <= c <= "\u09FF")

    total = len(text)
    if total == 0:
        return "en"

    devanagari_ratio = devanagari_chars / total

    # Marathi-specific words that don't appear in Hindi
    MARATHI_MARKERS = [
        "आहे", "नाही", "होते", "आणि", "मला", "तुम्ही", "कसे", "काय",
        "dukhtay", "thakwa", "taap", "kasa", "watato", "aahe", "nahi",
    ]
    text_lower = text.lower()
    marathi_hits = sum(1 for w in MARATHI_MARKERS if w in text_lower or w in text)

    scores = {
        "ta": tamil_chars   / total,
        "te": telugu_chars  / total,
        "kn": kannada_chars / total,
        "bn": bengali_chars / total,
    }

    # Decide between Hindi and Marathi for Devanagari script
    if devanagari_ratio > 0.1:
        # If 2+ Marathi marker words found, classify as Marathi
        if marathi_hits >= 2:
            scores["mr"] = devanagari_ratio
        else:
            scores["hi"] = devanagari_ratio

    if not scores:
        return "en"

    best = max(scores, key=scores.get)
    return best if scores[best] > 0.1 else "en"
