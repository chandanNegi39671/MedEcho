"""
Fine-Tune Data Prep
────────────────────
Converts augmented dataset → OpenAI fine-tuning JSONL format.

OpenAI fine-tuning expects each line to be:
{
  "messages": [
    {"role": "system",    "content": "..."},
    {"role": "user",      "content": "transcript..."},
    {"role": "assistant", "content": "{structured EMR JSON}"}
  ]
}

Also splits data into train (80%) / validation (20%) sets.

Usage:
    python -m evaluation.finetune_prep --input augmented_data.json

Output:
    finetune_train.jsonl    — upload to OpenAI for fine-tuning
    finetune_val.jsonl      — validation set
    finetune_stats.json     — dataset statistics
"""

import json
import random
import argparse
import os
import sys
from typing import Optional
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FINETUNE_SYSTEM_PROMPT = """You are a medical scribe for Indian outpatient clinics.
Extract structured EMR data from doctor-patient consultation transcripts.
Return ONLY valid JSON in concise clinical note style.
Transcript may be in Hindi, Marathi, Tamil or mixed — output always in English.

JSON schema:
{
  "chiefComplaint": "concise phrase",
  "hpi": "symptoms; duration; severity",
  "pastHistory": "conditions or null",
  "medications": ["Drug Dose Frequency Duration"],
  "allergies": "substance or NKDA or null",
  "examFindings": "vitals and findings",
  "diagnosis": "Diagnosis (ICD-10)",
  "plan": "investigations; treatment; advice",
  "followUpDays": <integer or null>,
  "diseaseRisk": {
    "fluProbability": 0.0, "migraineProbability": 0.0,
    "fatigueProbability": 0.0, "diabetesProbability": 0.0,
    "hypertensionProbability": 0.0, "notes": null
  },
  "hallucinationCheck": {"isHallucinated": false, "details": null, "confidenceScore": 1.0}
}"""


def normalize_ground_truth(gt: dict) -> dict:
    """
    Convert Eka dataset ground truth keys → our EMR JSON structure.
    Eka uses snake_case, we use camelCase.
    """
    medications_raw = gt.get("medications", gt.get("medication", ""))
    if isinstance(medications_raw, str) and medications_raw:
        medications = [m.strip() for m in medications_raw.split(",") if m.strip()]
    elif isinstance(medications_raw, list):
        medications = medications_raw
    else:
        medications = []

    return {
        "chiefComplaint": gt.get("chief_complaint") or gt.get("chiefComplaint"),
        "hpi":            gt.get("history_of_present_illness") or gt.get("hpi"),
        "pastHistory":    gt.get("past_history") or gt.get("pastHistory"),
        "medications":    medications,
        "allergies":      gt.get("allergies"),
        "examFindings":   gt.get("examination_findings") or gt.get("examFindings"),
        "diagnosis":      gt.get("diagnosis"),
        "plan":           gt.get("plan"),
        "followUpDays":   gt.get("follow_up_days") or gt.get("followUpDays"),
        "diseaseRisk": {
            "fluProbability":          0.0,
            "migraineProbability":     0.0,
            "fatigueProbability":      0.0,
            "diabetesProbability":     0.0,
            "hypertensionProbability": 0.0,
            "notes":                   None
        },
        "hallucinationCheck": {
            "isHallucinated":  False,
            "details":         None,
            "confidenceScore": 1.0
        }
    }


def sample_to_finetune_row(sample: dict) -> Optional[dict]:
    """Convert one augmented sample to OpenAI fine-tune message format."""
    transcript   = sample.get("transcript", "")
    ground_truth = sample.get("ground_truth", {})

    if not transcript.strip():
        return None

    normalized = normalize_ground_truth(ground_truth)

    # Skip samples where critical fields are all null
    has_content = any([
        normalized.get("chiefComplaint"),
        normalized.get("diagnosis"),
        normalized.get("hpi"),
    ])
    if not has_content:
        return None

    return {
        "messages": [
            {
                "role":    "system",
                "content": FINETUNE_SYSTEM_PROMPT
            },
            {
                "role":    "user",
                "content": f"Consultation transcript:\n\n{transcript}"
            },
            {
                "role":    "assistant",
                "content": json.dumps(normalized, ensure_ascii=False)
            }
        ]
    }


def estimate_tokens(text: str) -> int:
    """Rough token estimate — ~4 chars per token."""
    return len(text) // 4


def prepare_finetune_data(
    input_file: str,
    train_file: str = "finetune_train.jsonl",
    val_file: str   = "finetune_val.jsonl",
    stats_file: str = "finetune_stats.json",
    val_split: float = 0.2,
    min_samples: int = 10,
):
    print(f"[FT Prep] Loading {input_file}...")

    with open(input_file) as f:
        raw_samples = json.load(f)

    print(f"[FT Prep] Loaded {len(raw_samples)} samples, converting...")

    rows = []
    skipped = 0
    for s in raw_samples:
        row = sample_to_finetune_row(s)
        if row:
            rows.append(row)
        else:
            skipped += 1

    print(f"[FT Prep] Converted: {len(rows)} valid | Skipped: {skipped}")

    if len(rows) < min_samples:
        print(f"[FT Prep] WARNING: Only {len(rows)} samples — fine-tuning needs at least {min_samples}")

    # Shuffle before split
    random.shuffle(rows)
    split_idx  = int(len(rows) * (1 - val_split))
    train_rows = rows[:split_idx]
    val_rows   = rows[split_idx:]

    # Write JSONL files
    def write_jsonl(path, data):
        with open(path, "w", encoding="utf-8") as f:
            for row in data:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    write_jsonl(train_file, train_rows)
    write_jsonl(val_file, val_rows)

    # Stats
    total_tokens = sum(
        estimate_tokens(json.dumps(r))
        for r in train_rows
    )
    estimated_cost = round(total_tokens / 1000 * 0.008, 2)   # ~$0.008 per 1K tokens for gpt-4o-mini

    stats = {
        "totalSamples":       len(rows),
        "trainSamples":       len(train_rows),
        "valSamples":         len(val_rows),
        "skipped":            skipped,
        "estimatedTokens":    total_tokens,
        "estimatedCostUSD":   estimated_cost,
        "trainFile":          train_file,
        "valFile":            val_file,
        "augmentationBreakdown": {},
    }

    # Augmentation type breakdown
    for s in raw_samples:
        aug_type = s.get("augmentation_type", "unknown")
        stats["augmentationBreakdown"][aug_type] = \
            stats["augmentationBreakdown"].get(aug_type, 0) + 1

    with open(stats_file, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\n{'='*55}")
    print(f"  FINE-TUNE DATA READY")
    print(f"{'='*55}")
    print(f"  Train samples     : {len(train_rows)}")
    print(f"  Val samples       : {len(val_rows)}")
    print(f"  Estimated tokens  : {total_tokens:,}")
    print(f"  Estimated cost    : ~${estimated_cost}")
    print(f"  Train file        : {train_file}")
    print(f"  Val file          : {val_file}")
    print(f"{'='*55}")
    print(f"\n  Next step: python -m evaluation.finetune_runner --train {train_file} --val {val_file}")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare fine-tuning data")
    parser.add_argument("--input", type=str, required=True, help="Augmented data JSON file")
    parser.add_argument("--train", type=str, default="finetune_train.jsonl")
    parser.add_argument("--val",   type=str, default="finetune_val.jsonl")
    parser.add_argument("--stats", type=str, default="finetune_stats.json")
    args = parser.parse_args()

    prepare_finetune_data(
        input_file=args.input,
        train_file=args.train,
        val_file=args.val,
        stats_file=args.stats,
    )
