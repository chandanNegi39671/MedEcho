"""
Hindi EMR Output Service
─────────────────────────
Translates generated English EMR fields to Hindi using Google Translate API.
Free tier — no API key needed for basic usage.
"""

from deep_translator import GoogleTranslator
from typing import Optional

# Fields to translate
TRANSLATE_FIELDS = [
    "chiefComplaint",
    "hpi",
    "examFindings",
    "diagnosis",
    "plan",
    "pastHistory",
    "allergies",
]

# Fields to keep in English (medical terms + doses)
KEEP_ENGLISH_FIELDS = [
    "medications",
    "followUpDays",
    "diseaseRisk",
    "hallucinationCheck",
    "_modelUsed",
    "_modelType",
]


def translate_to_hindi(text: str) -> str:
    """Translate a single string to Hindi."""
    if not text or not str(text).strip():
        return text
    try:
        translated = GoogleTranslator(source='en', target='hi').translate(str(text))
        return translated or text
    except Exception as e:
        print(f"[HindiEMR] Translation failed: {e}")
        return text  # Return original if fails


def emr_to_hindi(emr: dict) -> dict:
    """
    Takes English EMR dict → returns Hindi EMR dict.
    Medications kept in English (doctor/pharmacist needs to read them).
    """
    hindi_emr = dict(emr)  # Copy original

    for field in TRANSLATE_FIELDS:
        value = emr.get(field)
        if not value:
            continue
        if isinstance(value, str) and value.strip():
            hindi_emr[field] = translate_to_hindi(value)

    # Add language tag
    hindi_emr["_language"] = "hi"
    hindi_emr["_note"] = "Medications kept in English for pharmacist readability."

    return hindi_emr


def emr_bilingual(emr: dict) -> dict:
    """
    Returns both English and Hindi side by side.
    Useful for doctor who wants to verify translation.
    """
    result = {}
    for field in TRANSLATE_FIELDS:
        value = emr.get(field, "")
        result[field] = {
            "en": value,
            "hi": translate_to_hindi(value) if value else ""
        }

    # Keep non-translated fields as-is
    for field in KEEP_ENGLISH_FIELDS:
        if field in emr:
            result[field] = emr[field]

    result["_language"] = "bilingual"
    return result
