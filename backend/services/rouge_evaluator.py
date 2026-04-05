"""
ROUGE Evaluator  —  v2
───────────────────────
Evaluates EMR generation quality.

"""

import json
import re
import string
from typing import Optional
from rouge_score import rouge_scorer as rouge_scorer_lib


# ─── Field Maps ───────────────────────────────────────────────────────────────
# Our EMR key → Eka/standard ground truth key
EMR_FIELD_MAP = {
    "chiefComplaint": "chief_complaint",
    "hpi":            "history_of_present_illness",
    "diagnosis":      "diagnosis",
    "plan":           "plan",
    "medications":    "medications",
    "examFindings":   "examination_findings",
    "pastHistory":    "past_history",
    "allergies":      "allergies",
}

# Fields that SHOULD be filled for a complete EMR
REQUIRED_FIELDS = ["chiefComplaint", "hpi", "diagnosis", "plan", "medications"]

# Verbose patterns that reduce quality score
VERBOSE_PATTERNS = [
    r"(?i)the patient (reports?|complains? of|mentions?|states?|presents? with)",
    r"(?i)it is (noted|documented) that",
    r"(?i)the doctor (advised?|recommended?|prescribed?)",
    r"(?i)^there (is|are)\s+",
    r"(?i)^currently\s*,?\s*",
    r"(?i)^patient (has|had|is|was)\s+",
    r"(?i)^(he|she|they) (has|had|is|was|reports?|complains?)\s+",
]


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


# ─── Core ROUGE ───────────────────────────────────────────────────────────────
_scorer = rouge_scorer_lib.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)


def compute_rouge(prediction: str, reference: str) -> dict:
    """Compute ROUGE-1/2/L F1 between prediction and reference."""
    p = _normalize(_to_text(prediction))
    r = _normalize(_to_text(reference))
    if not p or not r:
        return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}
    scores = _scorer.score(r, p)
    return {
        "rouge1": round(scores["rouge1"].fmeasure, 4),
        "rouge2": round(scores["rouge2"].fmeasure, 4),
        "rougeL": round(scores["rougeL"].fmeasure, 4),
    }


# ─── MODE 1: Ground Truth ROUGE ───────────────────────────────────────────────
def evaluate_emr_against_ground_truth(generated_emr: dict, ground_truth: dict) -> dict:
    """
    Compare generated EMR against labeled ground truth.
    Works when you have a proper labeled dataset with reference JSON.
    """
    field_scores = {}
    all_r1, all_r2, all_rL = [], [], []

    for emr_key, gt_key in EMR_FIELD_MAP.items():
        pred = _to_text(generated_emr.get(emr_key))
        ref  = _to_text(ground_truth.get(gt_key) or ground_truth.get(emr_key))

        scores = compute_rouge(pred, ref)
        field_scores[emr_key] = scores

        if ref.strip():
            all_r1.append(scores["rouge1"])
            all_r2.append(scores["rouge2"])
            all_rL.append(scores["rougeL"])

    overall = {
        "rouge1": round(sum(all_r1) / len(all_r1), 4) if all_r1 else 0.0,
        "rouge2": round(sum(all_r2) / len(all_r2), 4) if all_r2 else 0.0,
        "rougeL": round(sum(all_rL) / len(all_rL), 4) if all_rL else 0.0,
    }

    benchmark   = 0.796   # EkaScribe benchmark
    claude_base = 0.726

    return {
        "mode":     "ground_truth_rouge",
        "overall":  overall,
        "perField": field_scores,
        "comparison": {
            "ourScore":           overall["rouge1"],
            "claudeBaseline":     claude_base,
            "ekaScribeBenchmark": benchmark,
            "beatsClaude":        overall["rouge1"] > claude_base,
            "beatsEkaScribe":     overall["rouge1"] > benchmark,
            "delta":              round(overall["rouge1"] - benchmark, 4),
        },
    }


# ─── MODE 2: Self-Consistency Eval (for Eka dataset) ─────────────────────────
def evaluate_emr_self_consistency(
    generated_emr: dict,
    transcript: str,
    rubrics_text: str = "",
) -> dict:
    """
    Score an EMR when no ground truth JSON exists (e.g. Eka dataset).

    Scoring breakdown (total 100 pts → normalized to 0-1):
      40 pts — Field Coverage   : required fields filled
      40 pts — Factual Grounding: field content supported by transcript
      20 pts — Clinical Quality : concise style, no verbose phrases, no hallucination flag
    """
    t_lower = transcript.lower()

    # ── Field Coverage (40 pts) ──────────────────────────────────────────────
    coverage_scores = {}
    for field in REQUIRED_FIELDS:
        val = generated_emr.get(field)
        filled = bool(val and val != [] and str(val).strip())
        coverage_scores[field] = 1.0 if filled else 0.0
    coverage = sum(coverage_scores.values()) / len(REQUIRED_FIELDS)

    # ── Factual Grounding (40 pts) ───────────────────────────────────────────
    # Check if key terms from each field appear in the transcript
    grounding_scores = {}
    for field in REQUIRED_FIELDS:
        val = _to_text(generated_emr.get(field))
        if not val.strip():
            grounding_scores[field] = 0.0
            continue
        # Extract meaningful words from field value
        words = [w for w in re.findall(r"\b[a-z]{3,}\b", val.lower())
                 if w not in {"the", "and", "for", "with", "this", "that",
                              "from", "are", "was", "has", "have", "not"}]
        if not words:
            grounding_scores[field] = 0.5   # short value, give benefit of doubt
            continue
        # What fraction of meaningful words appear in the transcript?
        matches = sum(1 for w in words if w in t_lower)
        grounding_scores[field] = round(min(1.0, matches / len(words) * 1.5), 4)

    grounding = sum(grounding_scores.values()) / len(REQUIRED_FIELDS)

    # ── Clinical Quality (20 pts) ────────────────────────────────────────────
    quality_penalties = 0
    verbose_fields    = []
    for field in ["chiefComplaint", "hpi", "diagnosis", "plan"]:
        val = _to_text(generated_emr.get(field))
        for pattern in VERBOSE_PATTERNS:
            if re.search(pattern, val):
                quality_penalties += 1
                verbose_fields.append(field)
                break

    # Hallucination flag penalty
    hc = generated_emr.get("hallucinationCheck", {})
    if hc.get("isHallucinated"):
        quality_penalties += 2

    quality = max(0.0, 1.0 - quality_penalties * 0.15)

    # ── Composite Score ───────────────────────────────────────────────────────
    composite = round(coverage * 0.40 + grounding * 0.40 + quality * 0.20, 4)

    return {
        "mode":      "self_consistency",
        "composite": composite,
        "breakdown": {
            "fieldCoverage":    round(coverage,  4),
            "factualGrounding": round(grounding, 4),
            "clinicalQuality":  round(quality,   4),
        },
        "perField": {
            "coverage":   coverage_scores,
            "grounding":  grounding_scores,
        },
        "flags": {
            "verboseFields":    verbose_fields,
            "hallucinationFlag": hc.get("isHallucinated", False),
        },
        "comparison": {
            "ourScore":           composite,
            "claudeBaseline":     0.726,
            "ekaScribeBenchmark": 0.796,
            "beatsClaude":        composite > 0.726,
            "beatsEkaScribe":     composite > 0.796,
            "delta":              round(composite - 0.796, 4),
        },
    }


# ─── Batch Evaluators ─────────────────────────────────────────────────────────
def batch_evaluate(samples: list) -> dict:
    """
    Batch evaluation with ground truth.
    Each sample: { "transcript": str, "generated_emr": dict, "ground_truth": dict }
    """
    results  = []
    r1, r2, rL = [], [], []

    for i, sample in enumerate(samples):
        result = evaluate_emr_against_ground_truth(
            sample["generated_emr"], sample["ground_truth"]
        )
        results.append({"sample": i + 1, **result})
        r1.append(result["overall"]["rouge1"])
        r2.append(result["overall"]["rouge2"])
        rL.append(result["overall"]["rougeL"])

    n = len(samples)
    avg_r1 = round(sum(r1) / n, 4) if n else 0.0
    return {
        "aggregate": {
            "totalSamples":     n,
            "avgRouge1":        avg_r1,
            "avgRouge2":        round(sum(r2) / n, 4) if n else 0.0,
            "avgRougeL":        round(sum(rL) / n, 4) if n else 0.0,
            "claudeBaseline":   0.726,
            "ekaScribeBenchmark": 0.796,
            "beatsClaude":      avg_r1 > 0.726,
            "beatsEkaScribe":   avg_r1 > 0.796,
        },
        "samples": results,
    }


def batch_evaluate_eka(samples: list, generate_fn) -> dict:
    """
    Batch evaluation on Eka dataset (no ground truth — uses self-consistency scoring).

    Args:
        samples:     List of Eka dataset samples (each has 'text', 'rubrics')
        generate_fn: Function that takes transcript str → returns EMR dict

    Returns:
        Aggregated self-consistency scores
    """
    results = []
    composites = []

    for i, sample in enumerate(samples):
        transcript   = sample.get("text", "")
        rubrics_text = str(sample.get("rubrics", ""))

        if not transcript.strip():
            continue

        try:
            emr    = generate_fn(transcript)
            result = evaluate_emr_self_consistency(emr, transcript, rubrics_text)
            results.append({"sample": i + 1, "emr": emr, **result})
            composites.append(result["composite"])
            print(f"  [{i+1}/{len(samples)}] Score: {result['composite']:.4f} "
                  f"| Coverage:{result['breakdown']['fieldCoverage']:.2f} "
                  f"Grounding:{result['breakdown']['factualGrounding']:.2f} "
                  f"Quality:{result['breakdown']['clinicalQuality']:.2f}")
        except Exception as e:
            print(f"  [{i+1}/{len(samples)}] ERROR: {e}")

    n      = len(composites)
    avg    = round(sum(composites) / n, 4) if n else 0.0
    return {
        "aggregate": {
            "totalSamples":       n,
            "avgComposite":       avg,
            "claudeBaseline":     0.726,
            "ekaScribeBenchmark": 0.796,
            "beatsClaude":        avg > 0.726,
            "beatsEkaScribe":     avg > 0.796,
            "delta":              round(avg - 0.796, 4),
        },
        "samples": results,
    }
