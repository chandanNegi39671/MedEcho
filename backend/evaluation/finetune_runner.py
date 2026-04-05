"""
Fine-Tune Runner
─────────────────
Uploads training data to OpenAI and launches a GPT-4o-mini fine-tune job.
Monitors progress and saves the final model ID for use in production.

Usage:
    python -m evaluation.finetune_runner --train finetune_train.jsonl --val finetune_val.jsonl

After completion:
    The fine-tuned model ID (ft:gpt-4o-mini-...) is saved to finetune_model.json
    Plug that ID into emr_router.py to use it automatically.

Cost estimate:
    ~800 samples × ~400 tokens = ~320K tokens
    GPT-4o-mini fine-tuning: ~$0.008 / 1K tokens = ~$2.50 total
"""

import time
import json
import argparse
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openai import OpenAI
from services.transcription import ai_settings

openai_client = OpenAI(api_key=ai_settings.OPENAI_API_KEY)

MODEL_OUTPUT_FILE = "finetune_model.json"


def upload_file(file_path: str, purpose: str = "fine-tune") -> str:
    """Upload a JSONL file to OpenAI and return file ID."""
    print(f"[FT Runner] Uploading {file_path}...")
    with open(file_path, "rb") as f:
        response = openai_client.files.create(file=f, purpose=purpose)
    file_id = response.id
    print(f"[FT Runner] Uploaded: {file_id}")
    return file_id


def launch_finetune(train_file_id: str, val_file_id: str, suffix: str = "mediscribe") -> str:
    """Launch a GPT-4o-mini fine-tune job and return job ID."""
    print(f"[FT Runner] Launching fine-tune job...")
    job = openai_client.fine_tuning.jobs.create(
        training_file=train_file_id,
        validation_file=val_file_id,
        model="gpt-4o-mini-2024-07-18",
        suffix=suffix,
        hyperparameters={
            "n_epochs": 3,              # 3 epochs — standard for this dataset size
            "batch_size": 4,
            "learning_rate_multiplier": 1.8
        }
    )
    job_id = job.id
    print(f"[FT Runner] Job launched: {job_id}")
    print(f"[FT Runner] Status: {job.status}")
    return job_id


def monitor_job(job_id: str, poll_interval: int = 60) -> dict:
    """
    Poll the fine-tune job until completion.
    Prints progress updates every poll_interval seconds.
    Fine-tuning typically takes 20-60 minutes.
    """
    print(f"\n[FT Runner] Monitoring job {job_id}")
    print(f"[FT Runner] Polling every {poll_interval}s (this usually takes 20-60 minutes)...")
    print(f"[FT Runner] You can close this and check back — job runs on OpenAI servers\n")

    start_time = time.time()

    while True:
        job = openai_client.fine_tuning.jobs.retrieve(job_id)
        elapsed = int(time.time() - start_time)
        elapsed_str = f"{elapsed // 60}m {elapsed % 60}s"

        print(f"  [{elapsed_str}] Status: {job.status}", end="")

        if job.trained_tokens:
            print(f" | Tokens trained: {job.trained_tokens:,}", end="")

        print()

        if job.status == "succeeded":
            print(f"\n[FT Runner] ✅ Fine-tuning COMPLETE!")
            print(f"[FT Runner] Model ID: {job.fine_tuned_model}")
            return job

        elif job.status in ("failed", "cancelled"):
            print(f"\n[FT Runner] ❌ Job {job.status}")
            if job.error:
                print(f"[FT Runner] Error: {job.error}")
            return job

        # Print recent events for visibility
        try:
            events = openai_client.fine_tuning.jobs.list_events(
                fine_tuning_job_id=job_id, limit=3
            )
            for event in reversed(events.data):
                if event.message and "loss" in event.message.lower():
                    print(f"  [event] {event.message}")
        except Exception:
            pass

        time.sleep(poll_interval)


def save_model_id(job, output_file: str = MODEL_OUTPUT_FILE):
    """Save the completed model ID for use in emr_router.py"""
    result = {
        "model_id":       job.fine_tuned_model,
        "job_id":         job.id,
        "status":         job.status,
        "trained_tokens": job.trained_tokens,
        "base_model":     "gpt-4o-mini-2024-07-18",
    }
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[FT Runner] Model info saved to {output_file}")
    return result


def run_finetune(train_file: str, val_file: str, monitor: bool = True):
    """Full pipeline: upload → launch → monitor → save."""
    # Upload files
    train_id = upload_file(train_file)
    val_id   = upload_file(val_file)

    # Launch job
    job_id = launch_finetune(train_id, val_id)

    if not monitor:
        print(f"\n[FT Runner] Job launched. Run with --job-id {job_id} to monitor later.")
        print(f"[FT Runner] Or check https://platform.openai.com/finetune")
        return {"job_id": job_id}

    # Monitor until done
    job = monitor_job(job_id)

    if job.status == "succeeded":
        result = save_model_id(job)
        print(f"\n{'='*55}")
        print(f"  FINE-TUNING COMPLETE")
        print(f"{'='*55}")
        print(f"  Model ID: {result['model_id']}")
        print(f"  Trained tokens: {result['trained_tokens']:,}")
        print(f"\n  Next step: python -m evaluation.benchmark --use-finetuned")
        print(f"{'='*55}")
        return result

    return {"job_id": job_id, "status": job.status}


def check_job(job_id: str):
    """Check status of an existing job by ID."""
    job = openai_client.fine_tuning.jobs.retrieve(job_id)
    print(f"Job ID     : {job.id}")
    print(f"Status     : {job.status}")
    print(f"Model      : {job.fine_tuned_model or 'not ready'}")
    print(f"Tokens     : {job.trained_tokens or 'N/A'}")

    if job.status == "succeeded" and job.fine_tuned_model:
        save_model_id(job)

    return job


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune GPT-4o-mini on clinical data")
    parser.add_argument("--train",      type=str, help="Training JSONL file")
    parser.add_argument("--val",        type=str, help="Validation JSONL file")
    parser.add_argument("--no-monitor", action="store_true", help="Launch job without monitoring")
    parser.add_argument("--check",      type=str, help="Check status of existing job ID")
    args = parser.parse_args()

    if args.check:
        check_job(args.check)
    elif args.train and args.val:
        run_finetune(
            train_file=args.train,
            val_file=args.val,
            monitor=not args.no_monitor
        )
    else:
        parser.print_help()
