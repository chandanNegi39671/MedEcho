"""
Data Augmentor
───────────────
Expands the Eka dataset from 156 → 800+ samples for fine-tuning.

Strategy — 5 augmentation types per sample:
  1. REPHRASE    — same case, different doctor/patient phrasing
  2. HINDI_MIX   — inject natural Hindi words into English transcript
  3. MARATHI_MIX — inject natural Marathi words into English transcript
  4. SEVERITY    — change symptom severity (mild/moderate/severe)
  5. DEMOGRAPHIC — change patient age, gender, background details

Usage:
    python -m evaluation.augment --samples 156 --output augmented_data.json

Output:
    JSON file with 800+ {transcript, ground_truth} pairs ready for fine-tuning
"""

import json
import time
import argparse
import os
import sys
from typing import Optional
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anthropic import Anthropic
from services.transcription import ai_settings

client = Anthropic(api_key=ai_settings.ANTHROPIC_API_KEY)

AUGMENTATION_TYPES = ["rephrase", "hindi_mix", "marathi_mix", "severity", "demographic"]

AUGMENT_SYSTEM = """You are a medical data augmentation expert for Indian clinical NLP.
You will receive a doctor-patient consultation transcript and its structured EMR ground truth.
Generate an augmented version based on the augmentation type requested.

RULES:
1. Return ONLY valid JSON with keys: "transcript" and "ground_truth"
2. The ground_truth must accurately reflect the NEW augmented transcript
3. Keep the same medical condition and core facts — only change what's asked
4. Augmented transcript should sound natural and realistic
5. Do not add medical information not in the original
"""

AUGMENT_PROMPTS = {
    "rephrase": """Augmentation type: REPHRASE
Rewrite the transcript with different but natural phrasing.
Change how the doctor asks questions and how the patient describes symptoms.
Keep all medical facts identical. Ground truth stays the same.""",

    "hindi_mix": """Augmentation type: HINDI_MIX  
Rewrite the transcript mixing natural Hindi words into the conversation.
Patient should speak in Hinglish (Hindi-English mix) as real patients do.
Doctor can use some Hindi too. Examples: "sir dard", "bukhaar", "pet mein dard", "aaram karo".
Update ground_truth if any field changes due to language.""",

    "marathi_mix": """Augmentation type: MARATHI_MIX
Rewrite mixing natural Marathi words. Examples: "dukhtay", "thakwa", "taap", "kasa watato".
Patient speaks in Marathi-English mix. Doctor responds naturally.
Update ground_truth accordingly.""",

    "severity": """Augmentation type: SEVERITY_CHANGE
Change the severity of the main symptom (mild → severe or severe → mild).
Update duration slightly (e.g. 2 days → 4 days).
Update the ground_truth to reflect the new severity in hpi, examFindings, plan.
Keep the same diagnosis unless severity change would alter it.""",

    "demographic": """Augmentation type: DEMOGRAPHIC_CHANGE
Change the patient demographic:
- Different age group (child/young adult/elderly)
- Different gender if appropriate
- Different city/background reference
Update ground_truth fields that would change (age-appropriate dosing, etc).
Keep the core medical condition the same.""",
}


def augment_single(transcript: str, ground_truth: dict, aug_type: str) -> Optional[dict]:
    """Generate one augmented sample."""
    prompt = f"""{AUGMENT_PROMPTS[aug_type]}

Original transcript:
{transcript}

Original ground_truth:
{json.dumps(ground_truth, indent=2)}

Return JSON with keys "transcript" and "ground_truth" only."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            temperature=0.7,   # Some creativity for augmentation
            system=AUGMENT_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        result = json.loads(text[start:end])

        # Validate structure
        if "transcript" not in result or "ground_truth" not in result:
            return None

        result["augmentation_type"] = aug_type
        result["source"] = "augmented"
        return result

    except Exception as e:
        print(f"    [!] Augmentation failed ({aug_type}): {e}")
        return None


def load_eka_dataset(num_samples: int) -> list:
    """Load from HuggingFace or use sample data."""
    try:
        from datasets import load_dataset
        print(f"[Augmentor] Loading {num_samples} Eka dataset samples...")
        ds = load_dataset(
            "ekacare/clinical_note_generation_dataset",
            split="train",
            trust_remote_code=True
        )
        return list(ds.select(range(min(num_samples, len(ds)))))
    except Exception as e:
        print(f"[Augmentor] HuggingFace load failed: {e}")
        print("[Augmentor] Using built-in samples for demonstration...")
        return _builtin_samples()


def _builtin_samples() -> list:
    """Minimal built-in samples to demonstrate augmentation."""
    return [
        {
            "transcript": "Doctor: What's the problem? Patient: Fever since yesterday, 101F. Dry cough and sore throat. Doctor: Any allergies? Patient: No. Doctor: Throat congested, chest clear. Viral URTI. Paracetamol 500mg TDS, cough syrup TDS. Return in 3 days if no improvement.",
            "chief_complaint": "Fever with sore throat and cough",
            "history_of_present_illness": "Fever 101F since yesterday; dry cough; sore throat",
            "diagnosis": "Viral upper respiratory tract infection",
            "plan": "Paracetamol 500mg TDS; cough syrup TDS; rest; review in 3 days",
            "medications": "Paracetamol 500mg, Cough syrup",
            "examination_findings": "Throat congested; chest clear",
            "past_history": None,
            "allergies": "NKDA",
        },
        {
            "transcript": "Doctor: Kya problem hai? Patient: Sir dard bahut tez, kal se, right side. Doctor: Nausea? Patient: Haan. Light se problem. Doctor: BP 124/80. Migraine hai. Sumatriptan do. 7 din baad aao.",
            "chief_complaint": "Right-sided headache",
            "history_of_present_illness": "Right-sided throbbing headache since yesterday; nausea; photophobia",
            "diagnosis": "Migraine without aura",
            "plan": "Sumatriptan 50mg at onset; rest in dark room; follow up 7 days",
            "medications": "Sumatriptan 50mg",
            "examination_findings": "BP 124/80 mmHg",
            "past_history": None,
            "allergies": None,
        },
    ]


def run_augmentation(num_samples: int = 156, output_file: str = "augmented_data.json"):
    """
    Main augmentation pipeline.
    Generates ~5x the input samples using 5 augmentation strategies.
    """
    raw_samples = load_eka_dataset(num_samples)
    print(f"[Augmentor] Loaded {len(raw_samples)} original samples")

    augmented = []
    total_to_generate = len(raw_samples) * len(AUGMENTATION_TYPES)
    generated = 0
    failed = 0

    for i, sample in enumerate(raw_samples):
        transcript  = sample.get("transcript") or sample.get("conversation", "")
        ground_truth = {k: v for k, v in sample.items() if k != "transcript"}

        if not transcript.strip():
            continue

        print(f"\n[{i+1}/{len(raw_samples)}] Original sample — generating {len(AUGMENTATION_TYPES)} variants...")

        # Always include original
        augmented.append({
            "transcript": transcript,
            "ground_truth": ground_truth,
            "augmentation_type": "original",
            "source": "eka_dataset"
        })

        for aug_type in AUGMENTATION_TYPES:
            print(f"  → {aug_type}...", end=" ", flush=True)
            result = augment_single(transcript, ground_truth, aug_type)

            if result:
                augmented.append(result)
                generated += 1
                print("✓")
            else:
                failed += 1
                print("✗")

            # Rate limit — Anthropic allows ~50 req/min on Sonnet
            time.sleep(1.2)

        # Save checkpoint every 10 samples
        if (i + 1) % 10 == 0:
            checkpoint = output_file.replace(".json", f"_checkpoint_{i+1}.json")
            with open(checkpoint, "w") as f:
                json.dump(augmented, f, indent=2)
            print(f"\n  [Checkpoint saved: {len(augmented)} samples → {checkpoint}]")

    # Final save
    with open(output_file, "w") as f:
        json.dump(augmented, f, indent=2)

    print(f"\n{'='*55}")
    print(f"  AUGMENTATION COMPLETE")
    print(f"{'='*55}")
    print(f"  Original samples    : {len(raw_samples)}")
    print(f"  Augmented generated : {generated}")
    print(f"  Failed              : {failed}")
    print(f"  Total dataset size  : {len(augmented)}")
    print(f"  Output file         : {output_file}")
    print(f"{'='*55}")
    print(f"\n  Next step: python -m evaluation.finetune_prep --input {output_file}")

    return augmented


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Augment Eka dataset for fine-tuning")
    parser.add_argument("--samples", type=int, default=156, help="Number of original samples to augment")
    parser.add_argument("--output",  type=str, default="augmented_data.json")
    args = parser.parse_args()
    run_augmentation(num_samples=args.samples, output_file=args.output)
