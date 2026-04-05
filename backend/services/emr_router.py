"""
EMR Router
───────────
Smart router that picks the best EMR generation model automatically.

Models available:
  1. Mistral Fine-tuned (HuggingFace) — negi3961/mediscribe-mistral, ROUGE: 68.9%
  2. Regex Fallback                   — if HF API fails

Routing logic:
  - If HF_API_TOKEN is set → use Mistral via HF Inference API
  - Otherwise → regex fallback
  - Can be forced with model="mistral" or model="fallback"
"""

import json
import os
import re
import sys
import httpx

# ─── Config ───────────────────────────────────────────────────────────────────
HF_MODEL_ID  = os.getenv("HF_MISTRAL_MODEL", "negi3961/mediscribe-mistral")
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
HF_API_URL   = f"https://api-inference.huggingface.co/models/{HF_MODEL_ID}"

MISTRAL_SYSTEM = """You are a medical scribe for Indian outpatient clinics.
Extract structured EMR data from doctor-patient consultation transcripts.

OUTPUT RULES:
1. Return ONLY valid JSON. No text before or after.
2. Concise clinical note style — short phrases, NOT full sentences.
3. ONLY include what is EXPLICITLY stated in the transcript. NEVER infer, assume, or hallucinate.
4. If a field is not mentioned in the transcript, set it to null or [].
5. Medications: "DrugName Dose Frequency Duration" e.g. "Tab Paracetamol 500mg TDS x3 days"
6. Diagnosis: include ICD-10 code if determinable.
7. Transcript may be Hindi/Marathi/Tamil/mixed — output ALWAYS in English.

JSON schema:
{
  "chiefComplaint": "one concise phrase or null",
  "hpi": "symptoms; duration; severity — semicolon separated or null",
  "pastHistory": "relevant conditions or null",
  "medications": ["Drug Dose Frequency Duration"],
  "allergies": "substance or NKDA or null",
  "examFindings": "vitals and key findings — brief or null",
  "diagnosis": "Diagnosis (ICD-10 code) or null",
  "plan": "investigations; medications; advice — semicolon separated or null",
  "followUpDays": <integer or null>,
  "diseaseRisk": {
    "fluProbability": <0.0-1.0>,
    "migraineProbability": <0.0-1.0>,
    "fatigueProbability": <0.0-1.0>,
    "diabetesProbability": <0.0-1.0>,
    "hypertensionProbability": <0.0-1.0>,
    "notes": "brief note if any > 0.7 else null"
  },
  "hallucinationCheck": {
    "isHallucinated": <boolean>,
    "details": "explanation or null",
    "confidenceScore": <0.0-1.0>
  }
}"""

# ─── Keyword map for hallucination filtering ──────────────────────────────────
FIELD_KEYWORDS = {
    "chiefComplaint": ["complaint", "fever", "pain", "cough", "patient", "problem",
                       "issue", "trouble", "headache", "vomit", "nausea", "dizziness"],
    "hpi":            ["since", "days", "weeks", "history", "presents", "started",
                       "ago", "duration", "months"],
    "pastHistory":    ["history", "past", "before", "previous", "chronic", "known",
                       "diagnosed", "earlier"],
    "diagnosis":      ["diagnosis", "diagnosed", "impression", "assessment", "condition",
                       "disease", "infection", "disorder"],
    "plan":           ["plan", "advice", "follow", "review", "refer", "rest", "fluids",
                       "return", "come back", "investigation"],
    "medications":    ["tablet", "tab", "syrup", "injection", "inj", "mg", "ml",
                       "capsule", "cap", "times", "tds", "bd", "od", "qid", "sos",
                       "paracetamol", "amoxicillin", "metformin", "atorvastatin"],
    "examFindings":   ["bp", "temp", "temperature", "pulse", "spo2", "oxygen",
                       "chest", "throat", "abdomen", "exam", "found", "noted"],
    "allergies":      ["allergy", "allergic", "nkda", "sensitive", "reaction"],
}


def _hallucination_filter(pred: dict, transcript: str) -> dict:
    """
    Post-processing: remove any field whose content has NO keyword support
    in the transcript. Sets removed fields to null instead of deleting them.
    """
    t_lower = transcript.lower()
    clean   = dict(pred)

    for field, keywords in FIELD_KEYWORDS.items():
        value = pred.get(field)
        if value is None or value == [] or value == "":
            continue
        if not any(kw in t_lower for kw in keywords):
            clean[field] = None if field != "medications" else []
            print(f"[HallucinationFilter] Cleared '{field}' — no transcript support")

    hc      = clean.get("hallucinationCheck", {})
    removed = [f for f in FIELD_KEYWORDS if pred.get(f) != clean.get(f)]
    if removed:
        hc["isHallucinated"]  = True
        hc["details"]         = f"Removed hallucinated fields: {', '.join(removed)}"
        hc["confidenceScore"] = max(0.0, hc.get("confidenceScore", 0.9) - 0.15 * len(removed))
        clean["hallucinationCheck"] = hc

    return clean


# ─── Fallback extractor ───────────────────────────────────────────────────────
def _fallback_extract(transcript: str) -> dict:
    """Simple regex fallback if HF API fails."""
    meds = re.findall(r'[A-Z][a-z]+\s+\d+\s*mg[^.,\n]*', transcript)
    return {
        "chiefComplaint": "",
        "hpi":            transcript[:200],
        "pastHistory":    None,
        "medications":    meds[:3] if meds else [],
        "allergies":      None,
        "examFindings":   None,
        "diagnosis":      None,
        "plan":           None,
        "followUpDays":   None,
        "diseaseRisk": {
            "fluProbability":          0.0,
            "migraineProbability":     0.0,
            "fatigueProbability":      0.0,
            "diabetesProbability":     0.0,
            "hypertensionProbability": 0.0,
            "notes":                   None,
        },
        "hallucinationCheck": {
            "isHallucinated":  False,
            "details":         None,
            "confidenceScore": 0.5,
        },
    }


# ─── Mistral HF Inference ─────────────────────────────────────────────────────
def _mistral_available() -> bool:
    return bool(HF_API_TOKEN)


def _mistral_generate(transcript: str, language: str) -> dict:
    """Call HuggingFace Inference API for negi3961/mediscribe-mistral."""
    lang_hint = f"\n[Language: {language} — output in English]" if language != "en" else ""
    prompt = (
        f"<s>[INST] {MISTRAL_SYSTEM}\n\n"
        f"Consultation transcript:{lang_hint}\n\n"
        f"{transcript.strip()} [/INST]"
    )

    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens":     512,
            "temperature":        0.01,
            "repetition_penalty": 1.1,
            "return_full_text":   False,
        }
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(HF_API_URL, headers=headers, json=payload)

    if resp.status_code == 503:
        raise RuntimeError("Model loading (cold start) — retry in ~20s")

    resp.raise_for_status()
    data = resp.json()

    text = data[0].get("generated_text", "") if isinstance(data, list) else data.get("generated_text", "")

    s = text.find("{")
    e = text.rfind("}") + 1
    if s == -1 or e == 0:
        raise ValueError(f"No JSON in Mistral output. Got: {text[:300]}")

    return json.loads(text[s:e])


# ─── Public Router API ────────────────────────────────────────────────────────
def generate_emr(
    transcript: str,
    language:   str = "en",
    model:      str = "auto",
) -> dict:
    """
    Generate structured EMR using the best available model.

    Args:
        transcript : Consultation transcript text
        language   : ISO 639-1 code (en/hi/mr/ta/te...)
        model      : "auto" | "mistral" | "fallback"

    Returns:
        EMR dict with _modelUsed, _modelType metadata
    """
    transcript = transcript[:2000]
    use_model  = _resolve_model(model)

    if use_model == "mistral":
        try:
            print(f"[Router] Using Mistral: {HF_MODEL_ID}")
            emr = _mistral_generate(transcript, language)
            emr = _hallucination_filter(emr, transcript)
            emr["_modelUsed"] = HF_MODEL_ID
            emr["_modelType"] = "mistral_finetuned_hf"
            return emr
        except Exception as e:
            print(f"[Router] Mistral failed ({e}) — falling back to regex")

    # Regex fallback
    print("[Router] Using regex fallback")
    emr = _fallback_extract(transcript)
    emr["_modelUsed"] = "fallback_regex"
    emr["_modelType"] = "fallback"
    return emr


def _resolve_model(model: str) -> str:
    if model == "fallback":
        return "fallback"
    if model == "mistral":
        if not _mistral_available():
            print("[Router] HF_API_TOKEN not set — falling back to regex")
            return "fallback"
        return "mistral"
    # auto: prefer Mistral if token configured
    return "mistral" if _mistral_available() else "fallback"


def get_model_status() -> dict:
    mistral_ok = _mistral_available()
    return {
        "mistral": {
            "available":      mistral_ok,
            "model":          HF_MODEL_ID,
            "type":           "mistral_finetuned_hf",
            "benchmarkRouge1": 0.6893,
            "benchmarkRougeL": 0.5726,
            "description":    "Fine-tuned Mistral-7B on medical transcripts via HuggingFace Inference API",
            "hfUrl":          f"https://huggingface.co/{HF_MODEL_ID}",
        },
        "fallback": {
            "available":   True,
            "model":       "regex_extractor",
            "type":        "fallback",
            "description": "Simple regex-based extractor — used when HF API unavailable",
        },
        "activeModel": "mistral" if mistral_ok else "fallback",
        "configNote":  "Set HF_API_TOKEN and HF_MISTRAL_MODEL in .env to enable Mistral",
    }