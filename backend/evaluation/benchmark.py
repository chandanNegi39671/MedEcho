"""
Eka Dataset Benchmark Runner
─────────────────────────────
Downloads the Eka Clinical Note Generation Dataset from HuggingFace,
runs our EMR engine on each transcript, and reports ROUGE scores
vs the published benchmark of 0.72.

Usage:
    python -m evaluation.benchmark --samples 20

Requirements:
    pip install datasets rouge-score
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.emr_engine import generate_emr_from_transcript
from services.rouge_evaluator import batch_evaluate


def load_eka_dataset(num_samples: int = 20):
    """Load samples from Eka clinical note generation dataset on HuggingFace."""
    try:
        from datasets import load_dataset
        print(f"[Benchmark] Loading Eka dataset ({num_samples} samples)...")
        dataset = load_dataset(
            "ekacare/clinical_note_generation_dataset",
            split="train",
            trust_remote_code=True
        )
        return list(dataset.select(range(min(num_samples, len(dataset)))))
    except Exception as e:
        print(f"[Benchmark] Could not load dataset: {e}")
        print("[Benchmark] Using built-in sample data for demonstration...")
        return _get_sample_data()


def _get_sample_data():
    """Fallback sample data mimicking Eka dataset structure."""
    return [
        {
            "transcript": "Doctor: What brings you in today? Patient: I have a severe headache for 3 days, mainly on the right side. Also feeling nauseous. Doctor: Any sensitivity to light? Patient: Yes, very much. Doctor: You have migraine. I'll prescribe Sumatriptan 50mg. Take it when the pain starts. Follow up in 7 days.",
            "chief_complaint": "Severe headache for 3 days",
            "history_of_present_illness": "Throbbing right-sided headache for 3 days with nausea and photophobia",
            "diagnosis": "Migraine without aura",
            "plan": "Sumatriptan 50mg at onset of pain. Follow up in 7 days.",
            "medications": "Sumatriptan 50mg",
            "examination_findings": None,
            "past_history": None,
            "allergies": None,
        },
        {
            "transcript": "Doctor: Kya takleef hai aapko? Patient: Bukhaar hai teen din se, 101 degree tak. Khaasi bhi hai. Doctor: Gala dekhta hoon. Haan, infection hai. Azithromycin likhta hoon, 500mg ek baar roz paanch din tak. Aur paracetamol bukhaar ke liye.",
            "chief_complaint": "Fever for 3 days with cough",
            "history_of_present_illness": "Fever up to 101°F for 3 days with cough",
            "diagnosis": "Upper respiratory tract infection",
            "plan": "Azithromycin 500mg once daily for 5 days. Paracetamol for fever.",
            "medications": "Azithromycin 500mg, Paracetamol 500mg",
            "examination_findings": "Throat — infection noted",
            "past_history": None,
            "allergies": None,
        },
    ]


def run_benchmark(num_samples: int = 20, output_file: str = None):
    """Run the full benchmark pipeline."""
    raw_samples = load_eka_dataset(num_samples)

    print(f"[Benchmark] Running EMR generation on {len(raw_samples)} samples...")
    prepared = []
    for i, sample in enumerate(raw_samples):
        transcript = sample.get("transcript", sample.get("conversation", ""))
        if not transcript:
            continue

        print(f"  [{i+1}/{len(raw_samples)}] Generating EMR...", end=" ")
        try:
            generated = generate_emr_from_transcript(transcript)
            prepared.append({
                "generated_emr": generated,
                "ground_truth": sample,
            })
            print("✓")
        except Exception as e:
            print(f"✗ ({e})")

    print(f"\n[Benchmark] Evaluating {len(prepared)} successful generations...")
    results = batch_evaluate(prepared)

    agg = results["aggregate"]
    print("\n" + "="*50)
    print("  MEDISCRIBE BENCHMARK RESULTS")
    print("="*50)
    print(f"  Samples Evaluated : {agg['totalSamples']}")
    print(f"  ROUGE-1 (ours)    : {agg['avgRouge1']:.4f}")
    print(f"  ROUGE-2 (ours)    : {agg['avgRouge2']:.4f}")
    print(f"  ROUGE-L (ours)    : {agg['avgRougeL']:.4f}")
    print(f"  Eka Benchmark     : {agg['benchmark']:.4f}")
    print(f"  Beats Benchmark?  : {'✅ YES' if agg['beatsBenchmark'] else '❌ NO'}")
    print("="*50)

    if output_file:
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n[Benchmark] Full results saved to {output_file}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MediScribe ROUGE Benchmark")
    parser.add_argument("--samples", type=int, default=20, help="Number of samples to evaluate")
    parser.add_argument("--output",  type=str, default="benchmark_results.json")
    args = parser.parse_args()

    run_benchmark(num_samples=args.samples, output_file=args.output)
