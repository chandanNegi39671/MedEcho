"""
EMR Engine — Stub
──────────────────
Claude API nahi hai — HuggingFace Inference API use ho raha hai.
Actual logic: services/emr_router.py
"""

from services.emr_router import generate_emr as _generate


def generate_emr_from_transcript(
    transcript: str,
    language:   str  = "en",
    two_pass:   bool = True
) -> dict:
    """
    Wrapper — routes to emr_router.py (HuggingFace Inference API).
    two_pass ignored — not needed with fine-tuned model.
    """
    return _generate(transcript=transcript, language=language)